"""Cliente da API do Mercado Livre: OAuth 2.0 + mensagens pos-venda.

Suporta VARIAS contas do Mercado Livre no mesmo app. Cada conta e guardada
com a chave "ml:{user_id}". As funcoes aceitam um user_id opcional; sem ele,
usam a primeira conta conectada.
"""
import time
from urllib.parse import urlencode

import httpx

from . import config, store

# cache em memoria para acelerar (instancia unica no Render Starter)
_TTL_PEDIDOS = 30          # segundos
_cache_pedidos: dict = {}  # uid -> (timestamp, resultados)
_TTL_UNREAD = 20
_cache_unread: dict = {}   # uid -> (timestamp, set de packs aguardando)
_migrado = False           # a migracao do token legado roda so 1x por processo


# --------------------------------------------------------------------------- #
# Contas conectadas
# --------------------------------------------------------------------------- #
def _migrar_legado() -> None:
    """Move um token antigo (chave 'ml', conta unica) para o novo formato. Roda 1x."""
    global _migrado
    if _migrado:
        return
    antigo = store.carregar("ml")
    if antigo and antigo.get("user_id"):
        store.salvar(f"ml:{antigo['user_id']}", antigo)
        store.remover("ml")
    _migrado = True


def contas() -> list[dict]:
    """Lista as contas do Mercado Livre conectadas."""
    _migrar_legado()
    return store.listar("ml:")


def _primeiro_uid() -> str | None:
    cs = contas()
    return str(cs[0]["user_id"]) if cs else None


# Apelido amigavel da loja (guardado separado do token, com chave "alias:{uid}")
def apelido_loja(user_id: str) -> str | None:
    rec = store.carregar(f"alias:{user_id}")
    return rec.get("apelido") if rec else None


def definir_apelido(user_id: str, apelido: str) -> None:
    if apelido:
        store.salvar(f"alias:{user_id}", {"apelido": apelido})
    else:
        store.remover(f"alias:{user_id}")


def nome_exibicao(acc: dict) -> str:
    """Nome amigavel da loja: apelido custom > nickname do ML > user_id."""
    uid = str(acc.get("user_id"))
    return apelido_loja(uid) or acc.get("nickname") or uid


def seller_id(user_id: str | None = None) -> str | None:
    return str(user_id) if user_id else _primeiro_uid()


def carregar_token(user_id: str | None = None) -> dict | None:
    uid = seller_id(user_id)
    return store.carregar(f"ml:{uid}") if uid else None


def _salvar_token(data: dict) -> None:
    data["expires_at"] = time.time() + int(data.get("expires_in", 0)) - 60
    store.salvar(f"ml:{data['user_id']}", data)


# --------------------------------------------------------------------------- #
# OAuth
# --------------------------------------------------------------------------- #
def montar_url_autorizacao(state: str) -> str:
    params = {
        "response_type": "code",
        "client_id": config.ML_CLIENT_ID,
        "redirect_uri": config.ML_REDIRECT_URI,
        "state": state,
    }
    return f"{config.ML_AUTHORIZE_URL}?{urlencode(params)}"


def _buscar_nickname(access_token: str) -> str | None:
    try:
        r = httpx.get(
            f"{config.ML_API_BASE}/users/me",
            headers={"Authorization": f"Bearer {access_token}"},
            timeout=15,
        )
        return r.json().get("nickname") if r.status_code == 200 else None
    except Exception:
        return None


def trocar_codigo_por_token(code: str) -> dict:
    resp = httpx.post(
        config.ML_TOKEN_URL,
        headers={"Accept": "application/json", "Content-Type": "application/x-www-form-urlencoded"},
        data={
            "grant_type": "authorization_code",
            "client_id": config.ML_CLIENT_ID,
            "client_secret": config.ML_CLIENT_SECRET,
            "code": code,
            "redirect_uri": config.ML_REDIRECT_URI,
        },
        timeout=30,
    )
    resp.raise_for_status()
    token = resp.json()
    token["nickname"] = _buscar_nickname(token["access_token"])
    _salvar_token(token)
    return token


def _renovar_token(user_id: str, refresh_token: str) -> dict:
    resp = httpx.post(
        config.ML_TOKEN_URL,
        headers={"Accept": "application/json", "Content-Type": "application/x-www-form-urlencoded"},
        data={
            "grant_type": "refresh_token",
            "client_id": config.ML_CLIENT_ID,
            "client_secret": config.ML_CLIENT_SECRET,
            "refresh_token": refresh_token,
        },
        timeout=30,
    )
    resp.raise_for_status()
    token = resp.json()
    antigo = store.carregar(f"ml:{user_id}") or {}
    token.setdefault("nickname", antigo.get("nickname"))
    _salvar_token(token)
    return token


def _access_token_valido(user_id: str | None = None) -> str:
    uid = seller_id(user_id)
    token = store.carregar(f"ml:{uid}") if uid else None
    if not token:
        raise RuntimeError("Sem conta do Mercado Livre. Faca login em /ml/login.")
    if time.time() >= token.get("expires_at", 0):
        token = _renovar_token(uid, token["refresh_token"])
    return token["access_token"]


# --------------------------------------------------------------------------- #
# Chamadas autenticadas (com retry no 401)
# --------------------------------------------------------------------------- #
def _req(metodo: str, path: str, token: str, **kwargs) -> httpx.Response:
    return httpx.request(
        metodo,
        f"{config.ML_API_BASE}{path}",
        headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
        timeout=30,
        **kwargs,
    )


def _chamar(metodo: str, path: str, user_id: str | None = None,
            token: dict | None = None, **kwargs) -> dict:
    """Faz a chamada. Se 'token' (dict da conta) for passado, evita reler do banco."""
    uid = str(user_id) if user_id else _primeiro_uid()
    if token is None:
        token = store.carregar(f"ml:{uid}")
        if not token:
            raise RuntimeError("Sem conta do Mercado Livre. Faca login em /ml/login.")
    acesso = token.get("access_token")
    if time.time() >= token.get("expires_at", 0):
        token = _renovar_token(uid, token["refresh_token"])
        acesso = token["access_token"]
    resp = _req(metodo, path, acesso, **kwargs)
    if resp.status_code == 401:
        if not token.get("refresh_token"):
            raise RuntimeError("Sessao do Mercado Livre expirada. Faca login em /ml/login.")
        try:
            novo = _renovar_token(uid, token["refresh_token"])
        except httpx.HTTPStatusError:
            raise RuntimeError("Sessao do Mercado Livre expirada. Faca login em /ml/login.")
        resp = _req(metodo, path, novo["access_token"], **kwargs)
    resp.raise_for_status()
    return resp.json() if resp.content else {}


def get(path: str, params: dict | None = None, user_id: str | None = None,
        token: dict | None = None) -> dict:
    return _chamar("GET", path, user_id=user_id, token=token, params=params or {})


def post(path: str, body: dict, user_id: str | None = None,
         token: dict | None = None) -> dict:
    return _chamar("POST", path, user_id=user_id, token=token, json=body)


# --------------------------------------------------------------------------- #
# Pedidos e mensagens (por conta)
# --------------------------------------------------------------------------- #
def listar_pedidos(limite: int = 15, user_id: str | None = None,
                   token: dict | None = None) -> list[dict]:
    uid = str(user_id) if user_id else _primeiro_uid()
    agora = time.time()
    cache = _cache_pedidos.get(uid)
    if cache and agora - cache[0] < _TTL_PEDIDOS:
        return cache[1]
    dados = get("/orders/search", {"seller": uid, "sort": "date_desc", "limit": limite},
                user_id=uid, token=token)
    resultados = dados.get("results", [])
    _cache_pedidos[uid] = (agora, resultados)
    return resultados


def listar_mensagens(pack_id: str, user_id: str | None = None,
                     token: dict | None = None) -> list[dict]:
    uid = str(user_id) if user_id else _primeiro_uid()
    dados = get(f"/messages/packs/{pack_id}/sellers/{uid}", {"tag": "post_sale"},
                user_id=uid, token=token)
    return dados.get("messages", [])


def packs_aguardando(user_id: str | None = None, token: dict | None = None) -> set:
    """Conjunto de packs com mensagens nao lidas (aguardando resposta da loja)."""
    uid = str(user_id) if user_id else _primeiro_uid()
    agora = time.time()
    cache = _cache_unread.get(uid)
    if cache and agora - cache[0] < _TTL_UNREAD:
        return cache[1]
    try:
        dados = get("/messages/unread", {"role": "seller", "tag": "post_sale"},
                    user_id=uid, token=token)
    except httpx.HTTPStatusError:
        dados = {}
    out = set()
    for r in (dados.get("results") or []):
        v = r.get("id") or r.get("pack_id") or r.get("resource")
        if v:
            out.add(str(v).rstrip("/").split("/")[-1])
    _cache_unread[uid] = (agora, out)
    return out


def enviar_mensagem(pack_id: str, comprador_id: str, texto: str,
                    user_id: str | None = None, token: dict | None = None) -> dict:
    uid = str(user_id) if user_id else _primeiro_uid()
    body = {"from": {"user_id": str(uid)}, "to": {"user_id": str(comprador_id)}, "text": texto}
    _cache_pedidos.pop(uid, None)  # forca atualizar a lista apos enviar
    return post(f"/messages/packs/{pack_id}/sellers/{uid}?tag=post_sale", body,
                user_id=uid, token=token)


def baixar_anexo(filename: str, user_id: str | None = None) -> tuple[bytes, str]:
    """Baixa um anexo de mensagem do Mercado Livre (a arte enviada pelo cliente)."""
    uid = seller_id(user_id)
    token = _access_token_valido(uid)
    r = httpx.get(
        f"{config.ML_API_BASE}/messages/attachments/{filename}",
        params={"tag": "post_sale", "site_id": "MLB"},
        headers={"Authorization": f"Bearer {token}"},
        timeout=60,
        follow_redirects=True,
    )
    r.raise_for_status()
    return r.content, r.headers.get("content-type", "application/octet-stream")
