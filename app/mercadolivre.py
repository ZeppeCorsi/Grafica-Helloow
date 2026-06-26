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
_TTL_CONTAS = 15
_cache_contas: dict = {"val": None, "ts": 0.0}
_TTL_ALIAS = 60
_cache_alias: dict = {}    # uid -> (timestamp, apelido)
_TTL_BUSCA = 60
_cache_busca: dict = {}    # codigo -> (timestamp, (pedido, uid))
_TTL_PERG = 25
_cache_perg: dict = {}     # (uid, status) -> (timestamp, perguntas)
_TTL_ITEM = 600
_cache_item: dict = {}     # item_id -> (timestamp, titulo)
_TTL_PERIODO = 300
_cache_periodo: dict = {}  # (uid, de, ate) -> (timestamp, pedidos)
_TTL_PRODUTOS = 300
_cache_produtos: dict = {}  # uid -> (timestamp, lista de produtos)
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
    """Lista as contas do Mercado Livre conectadas (com cache curto)."""
    _migrar_legado()
    agora = time.time()
    if _cache_contas["val"] is None or agora - _cache_contas["ts"] > _TTL_CONTAS:
        _cache_contas["val"] = store.listar("ml:")
        _cache_contas["ts"] = agora
    return _cache_contas["val"]


def _primeiro_uid() -> str | None:
    cs = contas()
    return str(cs[0]["user_id"]) if cs else None


# Apelido amigavel da loja (guardado separado do token, com chave "alias:{uid}")
def apelido_loja(user_id: str) -> str | None:
    uid = str(user_id)
    agora = time.time()
    c = _cache_alias.get(uid)
    if c and agora - c[0] < _TTL_ALIAS:
        return c[1]
    rec = store.carregar(f"alias:{uid}")
    ap = rec.get("apelido") if rec else None
    _cache_alias[uid] = (agora, ap)
    return ap


def definir_apelido(user_id: str, apelido: str) -> None:
    uid = str(user_id)
    if apelido:
        store.salvar(f"alias:{uid}", {"apelido": apelido})
    else:
        store.remover(f"alias:{uid}")
    _cache_alias.pop(uid, None)


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
    _cache_contas["ts"] = 0.0  # forca recarregar as contas com o token novo


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
                   token: dict | None = None, pagina: int = 1) -> list[dict]:
    uid = str(user_id) if user_id else _primeiro_uid()
    pagina = max(1, pagina)
    chave = f"{uid}:{pagina}"
    agora = time.time()
    cache = _cache_pedidos.get(chave)
    if cache and agora - cache[0] < _TTL_PEDIDOS:
        return cache[1]
    offset = (pagina - 1) * limite
    dados = get("/orders/search",
                {"seller": uid, "sort": "date_desc", "limit": limite, "offset": offset},
                user_id=uid, token=token)
    resultados = dados.get("results", [])
    _cache_pedidos[chave] = (agora, resultados)
    return resultados


def pedidos_periodo(de: str, ate: str, user_id: str | None = None,
                    token: dict | None = None, max_paginas: int = 80) -> list[dict]:
    """Todos os pedidos de uma conta entre as datas de/ate (YYYY-MM-DD)."""
    uid = str(user_id) if user_id else _primeiro_uid()
    chave = (uid, de, ate)
    agora = time.time()
    cache = _cache_periodo.get(chave)
    if cache and agora - cache[0] < _TTL_PERIODO:
        return cache[1]
    todos: list[dict] = []
    offset = 0
    while offset < max_paginas * 50:
        params = {
            "seller": uid, "sort": "date_desc", "limit": 50, "offset": offset,
            "order.date_created.from": f"{de}T00:00:00.000-00:00",
            "order.date_created.to": f"{ate}T23:59:59.999-00:00",
        }
        dados = get("/orders/search", params, user_id=uid, token=token)
        res = dados.get("results", [])
        todos.extend(res)
        if len(res) < 50:
            break
        offset += 50
    _cache_periodo[chave] = (agora, todos)
    return todos


def obter_pedido(order_id: str, user_id: str | None = None,
                 token: dict | None = None) -> dict | None:
    """Busca um pedido do ML pelo codigo (ID do pedido). None se nao for desta conta."""
    try:
        return get(f"/orders/{order_id}", user_id=user_id, token=token)
    except httpx.HTTPStatusError:
        return None


def buscar_pedido_cod(codigo: str, contas_lista: list[dict]) -> tuple:
    """Acha um pedido pelo codigo em qualquer conta (com cache). Retorna (pedido, uid)."""
    agora = time.time()
    c = _cache_busca.get(codigo)
    if c and agora - c[0] < _TTL_BUSCA:
        return c[1]
    achado = (None, None)
    for acc in contas_lista:
        o = obter_pedido(codigo, token=acc)
        if o:
            achado = (o, str(acc["user_id"]))
            break
    _cache_busca[codigo] = (agora, achado)
    return achado


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
        # resource = "/packs/{PACK_ID}/sellers/{SELLER_ID}" -> extrai o PACK
        partes = str(r.get("resource", "")).strip("/").split("/")
        if "packs" in partes:
            i = partes.index("packs")
            if i + 1 < len(partes):
                out.add(partes[i + 1])
        elif r.get("id") or r.get("pack_id"):
            out.add(str(r.get("id") or r.get("pack_id")))
    _cache_unread[uid] = (agora, out)
    return out


def enviar_mensagem(pack_id: str, comprador_id: str, texto: str,
                    user_id: str | None = None, token: dict | None = None) -> dict:
    uid = str(user_id) if user_id else _primeiro_uid()
    body = {"from": {"user_id": str(uid)}, "to": {"user_id": str(comprador_id)}, "text": texto}
    for k in list(_cache_pedidos):  # limpa o cache de todas as paginas dessa loja
        if k.startswith(f"{uid}:"):
            _cache_pedidos.pop(k, None)
    _cache_unread.pop(uid, None)
    return post(f"/messages/packs/{pack_id}/sellers/{uid}?tag=post_sale", body,
                user_id=uid, token=token)


# --------------------------------------------------------------------------- #
# Perguntas (pre-venda, no anuncio)
# --------------------------------------------------------------------------- #
def listar_perguntas(user_id: str | None = None, token: dict | None = None,
                     status: str = "unanswered", limite: int = 30) -> list[dict]:
    uid = str(user_id) if user_id else _primeiro_uid()
    chave = (uid, status)
    agora = time.time()
    cache = _cache_perg.get(chave)
    if cache and agora - cache[0] < _TTL_PERG:
        return cache[1]
    params = {"seller_id": uid, "api_version": "4", "limit": limite}
    if status and status != "all":
        params["status"] = status.upper()  # UNANSWERED / ANSWERED
    dados = get("/questions/search", params, user_id=uid, token=token)
    perguntas = dados.get("questions", [])
    _cache_perg[chave] = (agora, perguntas)
    return perguntas


def titulo_item(item_id: str, user_id: str | None = None, token: dict | None = None) -> str:
    if not item_id:
        return "-"
    agora = time.time()
    c = _cache_item.get(item_id)
    if c and agora - c[0] < _TTL_ITEM:
        return c[1]
    try:
        d = get(f"/items/{item_id}", {"attributes": "title"}, user_id=user_id, token=token)
        titulo = d.get("title") or str(item_id)
    except httpx.HTTPStatusError:
        titulo = str(item_id)
    _cache_item[item_id] = (agora, titulo)
    return titulo


def responder_pergunta(question_id: str, texto: str,
                       user_id: str | None = None, token: dict | None = None) -> dict:
    uid = str(user_id) if user_id else _primeiro_uid()
    _cache_perg.pop((uid, "unanswered"), None)
    _cache_perg.pop((uid, "answered"), None)
    _cache_perg.pop((uid, "all"), None)
    return post("/answers", {"question_id": int(question_id), "text": texto},
                user_id=uid, token=token)


# --------------------------------------------------------------------------- #
# Produtos (anuncios do vendedor)
# --------------------------------------------------------------------------- #
def _todos_item_ids(uid: str, token: dict | None) -> list[str]:
    """IDs de todos os anuncios da conta. Usa offset (rapido e confiavel, ate
    1000 anuncios) e cai para 'scan' so quando houver mais de 1000."""
    primeiro = get(f"/users/{uid}/items/search", {"limit": 50, "offset": 0},
                   user_id=uid, token=token)
    total = int((primeiro.get("paging") or {}).get("total") or 0)
    ids: list[str] = list(primeiro.get("results") or [])

    if total <= 1000:
        offset = 50
        while offset < total:
            dados = get(f"/users/{uid}/items/search", {"limit": 50, "offset": offset},
                        user_id=uid, token=token)
            res = dados.get("results") or []
            if not res:
                break
            ids.extend(res)
            offset += 50
        return ids

    # mais de 1000 anuncios: paginacao 'scan' (sem o teto de offset do ML)
    ids = []
    scroll: str | None = None
    for _ in range(400):  # teto de seguranca: 400 x 100 = 40 mil anuncios
        params = {"search_type": "scan", "limit": 100}
        if scroll:
            params["scroll_id"] = scroll
        dados = get(f"/users/{uid}/items/search", params, user_id=uid, token=token)
        res = dados.get("results") or []
        scroll = dados.get("scroll_id")
        if not res:
            break
        ids.extend(res)
        if not scroll:
            break
    return ids


def _detalhes_itens(ids: list[str], uid: str, token: dict | None) -> list[dict]:
    """Detalhes dos anuncios em lotes de 20 (multiget /items?ids=...)."""
    attrs = ("id,title,price,available_quantity,status,sold_quantity,"
             "seller_custom_field,secure_thumbnail,thumbnail,permalink")
    out: list[dict] = []
    for i in range(0, len(ids), 20):
        lote = ids[i:i + 20]
        try:
            dados = get("/items", {"ids": ",".join(lote), "attributes": attrs},
                        user_id=uid, token=token)
        except httpx.HTTPStatusError:
            continue
        for entry in (dados if isinstance(dados, list) else []):
            if entry.get("code") == 200 and entry.get("body"):
                out.append(entry["body"])
    return out


def listar_produtos(user_id: str | None = None, token: dict | None = None) -> list[dict]:
    """Todos os anuncios de uma conta (id, titulo, preco, sku, status, foto). Cache 5min."""
    uid = str(user_id) if user_id else _primeiro_uid()
    agora = time.time()
    cache = _cache_produtos.get(uid)
    if cache and agora - cache[0] < _TTL_PRODUTOS:
        return cache[1]
    ids = _todos_item_ids(uid, token)
    itens = _detalhes_itens(ids, uid, token)
    itens.sort(key=lambda p: (p.get("title") or "").lower())
    _cache_produtos[uid] = (agora, itens)
    return itens


def invalidar_produtos(user_id: str | None = None) -> None:
    if user_id:
        _cache_produtos.pop(str(user_id), None)
    else:
        _cache_produtos.clear()


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
