"""Cliente da API do Bling v3: OAuth 2.0 + busca de pedidos.

Fluxo:
  1. montar_url_autorizacao()  -> usuario aprova no Bling e volta com um "code"
  2. trocar_codigo_por_token() -> troca o code por access_token + refresh_token
  3. get()                     -> faz chamadas autenticadas, renovando o token sozinho
"""
import base64
import json
import time
from typing import Any
from urllib.parse import urlencode

import httpx

from . import config, store


# --------------------------------------------------------------------------- #
# Armazenamento do token (arquivo local OU banco, ver app/store.py).
# --------------------------------------------------------------------------- #
def _salvar_token(data: dict[str, Any]) -> None:
    # guardamos tambem o momento de expiracao calculado, para saber quando renovar
    data["expires_at"] = time.time() + int(data.get("expires_in", 0)) - 60
    store.salvar("bling", data)


def carregar_token() -> dict[str, Any] | None:
    return store.carregar("bling")


def _auth_basic_header() -> dict[str, str]:
    raw = f"{config.CLIENT_ID}:{config.CLIENT_SECRET}".encode()
    return {"Authorization": "Basic " + base64.b64encode(raw).decode()}


# --------------------------------------------------------------------------- #
# Passo 1: URL para o usuario autorizar o app
# --------------------------------------------------------------------------- #
def montar_url_autorizacao(state: str) -> str:
    params = {
        "response_type": "code",
        "client_id": config.CLIENT_ID,
        "state": state,
        "redirect_uri": config.REDIRECT_URI,
    }
    return f"{config.AUTHORIZE_URL}?{urlencode(params)}"


# --------------------------------------------------------------------------- #
# Passo 2: trocar o "code" por um token
# --------------------------------------------------------------------------- #
def trocar_codigo_por_token(code: str) -> dict[str, Any]:
    resp = httpx.post(
        config.TOKEN_URL,
        headers={
            **_auth_basic_header(),
            "Content-Type": "application/x-www-form-urlencoded",
            "Accept": "application/json",
        },
        data={
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": config.REDIRECT_URI,
        },
        timeout=30,
    )
    resp.raise_for_status()
    token = resp.json()
    _salvar_token(token)
    return token


def _renovar_token(refresh_token: str) -> dict[str, Any]:
    resp = httpx.post(
        config.TOKEN_URL,
        headers={
            **_auth_basic_header(),
            "Content-Type": "application/x-www-form-urlencoded",
            "Accept": "application/json",
        },
        data={"grant_type": "refresh_token", "refresh_token": refresh_token},
        timeout=30,
    )
    resp.raise_for_status()
    token = resp.json()
    _salvar_token(token)
    return token


def _access_token_valido() -> str:
    token = carregar_token()
    if not token:
        raise RuntimeError("Nenhum token salvo. Faca login em /login primeiro.")
    if time.time() >= token.get("expires_at", 0):
        token = _renovar_token(token["refresh_token"])
    return token["access_token"]


# --------------------------------------------------------------------------- #
# Passo 3: chamadas autenticadas
# --------------------------------------------------------------------------- #
def _fazer_get(path: str, access_token: str, params: dict[str, Any] | None):
    return httpx.get(
        f"{config.API_BASE}{path}",
        headers={"Authorization": f"Bearer {access_token}", "Accept": "application/json"},
        params=params or {},
        timeout=30,
    )


def get(path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
    resp = _fazer_get(path, _access_token_valido(), params)

    # Se o Bling disser que o token e invalido/expirado, renova e tenta de novo (1x).
    if resp.status_code == 401:
        token = carregar_token()
        if not token or not token.get("refresh_token"):
            raise RuntimeError("Sessao expirada. Faca login em /login novamente.")
        try:
            novo = _renovar_token(token["refresh_token"])
        except httpx.HTTPStatusError:
            # refresh_token tambem expirou -> precisa reconectar
            raise RuntimeError("Sessao expirada. Faca login em /login novamente.")
        resp = _fazer_get(path, novo["access_token"], params)

    resp.raise_for_status()
    return resp.json()


def listar_pedidos(pagina: int = 1, limite: int = 20) -> list[dict[str, Any]]:
    """Retorna os pedidos de venda (lista resumida da API)."""
    dados = get("/pedidos/vendas", {"pagina": pagina, "limite": limite})
    return dados.get("data", [])


def obter_pedido(pedido_id: int | str) -> dict[str, Any]:
    """Detalhe completo de um pedido (itens, contato, loja, situacao)."""
    return get(f"/pedidos/vendas/{pedido_id}").get("data", {})


def obter_contato(contato_id: int | str) -> dict[str, Any]:
    """Dados do cliente (nome, telefone, email). Requer o escopo 'Contatos'."""
    return get(f"/contatos/{contato_id}").get("data", {})


def normalizar_whatsapp(telefone: str | None) -> str | None:
    """Converte um telefone em formato para link wa.me (so digitos, com DDI 55)."""
    if not telefone:
        return None
    digitos = "".join(c for c in telefone if c.isdigit())
    if not digitos:
        return None
    if not digitos.startswith("55"):
        digitos = "55" + digitos
    return digitos
