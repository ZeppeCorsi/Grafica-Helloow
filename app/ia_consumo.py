"""Contador de consumo de IA (metering para cobranca).

Cada interacao de IA (analise financeira, leitura de boleto/nota por foto) e
registrada aqui com o modelo usado e os tokens. Calcula o custo estimado em R$
e serve de base para cobrar o cliente (pacote mensal + excedente no cartao).

Banco na nuvem (DATABASE_URL) ou arquivo local, igual aos outros modulos.
Quando a aba de IA for ligada de verdade, basta chamar `registrar(...)` apos
cada chamada a API da Claude (la temos os tokens reais via response.usage).
"""
import json
import os
from datetime import datetime

from . import config, store

DATABASE_URL = os.getenv("DATABASE_URL", "")
_ARQ = config.BASE_DIR / "ia_consumo.json"

# Preco da API da Claude por 1 milhao de tokens, em USD (jun/2026).
PRECOS = {
    "haiku":  {"in": 1.0, "out": 5.0,  "rotulo": "Haiku (rapido/barato)"},
    "sonnet": {"in": 3.0, "out": 15.0, "rotulo": "Sonnet (equilibrio)"},
    "opus":   {"in": 5.0, "out": 25.0, "rotulo": "Opus (premium)"},
}

# Tokens tipicos por tipo de interacao (estimativa usada quando ainda nao temos
# os tokens reais - p.ex. no botao de simulacao). A foto de um boleto/nota
# "pesa" ~1.600-2.000 tokens de entrada.
PERFIS = {
    "texto": {"in": 4000, "out": 1000, "rotulo": "Analise (texto)"},
    "foto":  {"in": 3500, "out": 600,  "rotulo": "Leitura de boleto/nota (foto)"},
}

CAMBIO_PADRAO = 5.50  # US$ -> R$


def _custo_usd(modelo: str, tokens_in: int, tokens_out: int) -> float:
    p = PRECOS.get(modelo, PRECOS["sonnet"])
    return tokens_in / 1_000_000 * p["in"] + tokens_out / 1_000_000 * p["out"]


# --------------------------------------------------------------------------- #
# Armazenamento (banco OU arquivo)
# --------------------------------------------------------------------------- #
if DATABASE_URL:
    import psycopg2

    def _conn():
        return psycopg2.connect(DATABASE_URL)

    def _init() -> None:
        with _conn() as c, c.cursor() as cur:
            cur.execute("CREATE TABLE IF NOT EXISTS ia_consumo ("
                        "id SERIAL PRIMARY KEY, ts TIMESTAMPTZ DEFAULT now(), "
                        "mes TEXT, tenant TEXT DEFAULT 'betinho', tipo TEXT, "
                        "modelo TEXT, tokens_in INTEGER, tokens_out INTEGER, "
                        "custo_usd DOUBLE PRECISION)")
            c.commit()

    _init()

    def _inserir(mes, tenant, tipo, modelo, tin, tout, cu) -> None:
        with _conn() as c, c.cursor() as cur:
            cur.execute("INSERT INTO ia_consumo (mes, tenant, tipo, modelo, "
                        "tokens_in, tokens_out, custo_usd) VALUES (%s,%s,%s,%s,%s,%s,%s)",
                        (mes, tenant, tipo, modelo, tin, tout, cu))
            c.commit()

    def _agregar(mes, tenant):
        with _conn() as c, c.cursor() as cur:
            cur.execute("SELECT tipo, COUNT(*), COALESCE(SUM(tokens_in),0), "
                        "COALESCE(SUM(tokens_out),0), COALESCE(SUM(custo_usd),0) "
                        "FROM ia_consumo WHERE mes=%s AND tenant=%s GROUP BY tipo",
                        (mes, tenant))
            return cur.fetchall()

else:

    def _load() -> dict:
        if _ARQ.exists():
            return json.loads(_ARQ.read_text(encoding="utf-8"))
        return {"seq": 0, "itens": []}

    def _save(d: dict) -> None:
        _ARQ.write_text(json.dumps(d, indent=2), encoding="utf-8")

    def _inserir(mes, tenant, tipo, modelo, tin, tout, cu) -> None:
        d = _load()
        d["seq"] += 1
        d["itens"].append({"id": d["seq"], "ts": datetime.now().isoformat(),
                           "mes": mes, "tenant": tenant, "tipo": tipo,
                           "modelo": modelo, "tokens_in": tin, "tokens_out": tout,
                           "custo_usd": cu})
        _save(d)

    def _agregar(mes, tenant):
        cont: dict = {}
        for r in _load()["itens"]:
            if r["mes"] != mes or r.get("tenant", "betinho") != tenant:
                continue
            a = cont.setdefault(r["tipo"], [0, 0, 0, 0.0])
            a[0] += 1
            a[1] += r.get("tokens_in", 0)
            a[2] += r.get("tokens_out", 0)
            a[3] += r.get("custo_usd", 0.0)
        return [(k, v[0], v[1], v[2], v[3]) for k, v in cont.items()]


# --------------------------------------------------------------------------- #
# API do modulo
# --------------------------------------------------------------------------- #
def registrar(tipo: str, modelo: str = "sonnet", tokens_in: int | None = None,
              tokens_out: int | None = None, tenant: str = "betinho") -> None:
    """Registra UMA interacao de IA. Se os tokens nao forem passados, usa a
    estimativa do perfil (texto/foto)."""
    perfil = PERFIS.get(tipo, PERFIS["texto"])
    tin = perfil["in"] if tokens_in is None else tokens_in
    tout = perfil["out"] if tokens_out is None else tokens_out
    cu = _custo_usd(modelo, tin, tout)
    mes = datetime.now().strftime("%Y-%m")
    _inserir(mes, tenant, tipo, modelo, tin, tout, cu)


def resumo_mes(mes: str | None = None, tenant: str = "betinho") -> dict:
    """Resumo do consumo do mes: total de interacoes, por tipo e custo (USD)."""
    mes = mes or datetime.now().strftime("%Y-%m")
    por_tipo: dict = {}
    total = tin = tout = 0
    custo_usd = 0.0
    for tipo, n, sin, sout, cu in _agregar(mes, tenant):
        por_tipo[tipo] = {"n": int(n), "custo_usd": float(cu)}
        total += int(n)
        tin += int(sin)
        tout += int(sout)
        custo_usd += float(cu)
    return {"mes": mes, "total": total, "tokens_in": tin, "tokens_out": tout,
            "custo_usd": custo_usd, "por_tipo": por_tipo}


def plano() -> dict:
    """Configuracao do pacote de IA vendido ao cliente."""
    c = store.carregar("ia_plano") or {}
    return {
        "limite": int(c.get("limite", 500)),
        "preco_pacote": float(c.get("preco_pacote", 79)),
        "excedente": float(c.get("excedente", 0.40)),
        "cambio": float(c.get("cambio", CAMBIO_PADRAO)),
        "markup": float(c.get("markup", 3.0)),
        "definido": bool(c),
    }


def salvar_plano(limite: int, preco_pacote: float, excedente: float,
                 cambio: float, markup: float) -> None:
    store.salvar("ia_plano", {
        "limite": int(limite), "preco_pacote": float(preco_pacote),
        "excedente": float(excedente), "cambio": float(cambio),
        "markup": float(markup),
    })
