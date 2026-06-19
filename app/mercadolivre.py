"""Cliente da API do Mercado Livre: OAuth 2.0 + mensagens pos-venda.

Diferencas em relacao ao Bling:
  - O redirect_uri PRECISA ser HTTPS (use ngrok no teste local).
  - client_id/secret vao no corpo do POST (nao em Basic Auth).
  - A resposta do token ja traz o "user_id" (= seller_id), que guardamos.

Fluxo:
  1. montar_url_autorizacao()  -> usuario aprova no Mercado Livre
  2. trocar_codigo_por_token() -> troca o code por access_token + refresh_token
  3. get()/post()             -> chamadas autenticadas, com refresh automatico
"""
import json
import time
from typing import Any
from urllib.parse import urlencode

import httpx

from . import config, store


# --------------------------------------------------------------------------- #
# Token (arquivo local OU banco, ver app/store.py)
# --------------------------------------------------------------------------- #
def _salvar_token(data: dict[str, Any]) -> None:
    data["expires_at"] = time.time() + int(data.get("expires_in", 0)) - 60
    store.salvar("ml", data)


def carregar_token() -> dict[str, Any] | None:
    return store.carregar("ml")


def seller_id() -> str | None:
    token = carregar_token()
    return str(token["user_id"]) if token and token.get("user_id") else None


# --------------------------------------------------------------------------- #
# Passo 1: URL de autorizacao
# --------------------------------------------------------------------------- #
def montar_url_autorizacao(state: str) -> str:
    params = {
        "response_type": "code",
        "client_id": config.ML_CLIENT_ID,
        "redirect_uri": config.ML_REDIRECT_URI,
        "state": state,
    }
    return f"{config.ML_AUTHORIZE_URL}?{urlencode(params)}"


# --------------------------------------------------------------------------- #
# Passo 2: trocar code por token / refresh
# --------------------------------------------------------------------------- #
def trocar_codigo_por_token(code: str) -> dict[str, Any]:
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
    _salvar_token(token)
    return token


def _renovar_token(refresh_token: str) -> dict[str, Any]:
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
    _salvar_token(token)
    return token


def _access_token_valido() -> str:
    token = carregar_token()
    if not token:
        raise RuntimeError("Sem token do Mercado Livre. Faca login em /ml/login.")
    if time.time() >= token.get("expires_at", 0):
        token = _renovar_token(token["refresh_token"])
    return token["access_token"]


# --------------------------------------------------------------------------- #
# Passo 3: chamadas autenticadas (com retry no 401)
# --------------------------------------------------------------------------- #
def _req(metodo: str, path: str, token: str, **kwargs) -> httpx.Response:
    return httpx.request(
        metodo,
        f"{config.ML_API_BASE}{path}",
        headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
        timeout=30,
        **kwargs,
    )


def _chamar(metodo: str, path: str, **kwargs) -> dict[str, Any]:
    resp = _req(metodo, path, _access_token_valido(), **kwargs)
    if resp.status_code == 401:
        token = carregar_token()
        if not token or not token.get("refresh_token"):
            raise RuntimeError("Sessao do Mercado Livre expirada. Faca login em /ml/login.")
        try:
            novo = _renovar_token(token["refresh_token"])
        except httpx.HTTPStatusError:
            raise RuntimeError("Sessao do Mercado Livre expirada. Faca login em /ml/login.")
        resp = _req(metodo, path, novo["access_token"], **kwargs)
    resp.raise_for_status()
    return resp.json() if resp.content else {}


def get(path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
    return _chamar("GET", path, params=params or {})


def post(path: str, body: dict[str, Any]) -> dict[str, Any]:
    return _chamar("POST", path, json=body)


# --------------------------------------------------------------------------- #
# Pedidos e mensagens
# --------------------------------------------------------------------------- #
def listar_pedidos(limite: int = 15) -> list[dict[str, Any]]:
    """Pedidos recentes do vendedor (cada um traz comprador e pack_id)."""
    sid = seller_id()
    dados = get("/orders/search", {"seller": sid, "sort": "date_desc", "limit": limite})
    return dados.get("results", [])


def listar_mensagens(pack_id: str) -> list[dict[str, Any]]:
    """Mensagens de uma conversa (pack). Para pedido sem pack, pack_id = order_id."""
    sid = seller_id()
    dados = get(f"/messages/packs/{pack_id}/sellers/{sid}", {"tag": "post_sale"})
    return dados.get("messages", [])


def enviar_mensagem(pack_id: str, comprador_id: str, texto: str) -> dict[str, Any]:
    """Responde o comprador dentro da conversa do Mercado Livre."""
    sid = seller_id()
    body = {
        "from": {"user_id": str(sid)},
        "to": {"user_id": str(comprador_id)},
        "text": texto,
    }
    return post(f"/messages/packs/{pack_id}/sellers/{sid}?tag=post_sale", body)
