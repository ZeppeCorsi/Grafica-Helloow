"""Custo de producao de cada produto (anuncio do Mercado Livre).

O usuario preenche o custo de cada anuncio na aba Produtos; esse custo alimenta
o calculo de margem (abas Resultado e Financeiro). Guardado por item_id do ML
(ex.: 'MLB1234567890'). Banco na nuvem (DATABASE_URL) ou arquivo local, com
cache em memoria (TTL) para nao bater no banco a cada pedido do Resultado.
"""
import json
import os
import time

from . import config

DATABASE_URL = os.getenv("DATABASE_URL", "")
_ARQ = config.BASE_DIR / "produtos_custo.json"
_TTL = 60
_cache: dict = {"val": None, "ts": 0.0}


if DATABASE_URL:
    import psycopg2

    def _conn():
        return psycopg2.connect(DATABASE_URL)

    def _init() -> None:
        with _conn() as c, c.cursor() as cur:
            cur.execute("CREATE TABLE IF NOT EXISTS produto_custo ("
                        "item_id TEXT PRIMARY KEY, custo DOUBLE PRECISION NOT NULL DEFAULT 0)")
            c.commit()

    _init()

    def _impl_todos() -> dict:
        with _conn() as c, c.cursor() as cur:
            cur.execute("SELECT item_id, custo FROM produto_custo")
            return {r[0]: float(r[1]) for r in cur.fetchall()}

    def _impl_varios(mapa: dict) -> None:
        # Em lote: 1 INSERT para os custos preenchidos + 1 DELETE para os vazios,
        # em vez de uma ida ao banco por produto (evita 500+ viagens EUA<->BR).
        from psycopg2.extras import execute_values
        sets = [(item_id, custo) for item_id, custo in mapa.items() if custo is not None]
        dels = [item_id for item_id, custo in mapa.items() if custo is None]
        with _conn() as c, c.cursor() as cur:
            if sets:
                execute_values(
                    cur,
                    "INSERT INTO produto_custo (item_id, custo) VALUES %s "
                    "ON CONFLICT (item_id) DO UPDATE SET custo = EXCLUDED.custo",
                    sets,
                )
            if dels:
                cur.execute("DELETE FROM produto_custo WHERE item_id = ANY(%s)", (dels,))
            c.commit()

else:

    def _load() -> dict:
        if _ARQ.exists():
            return json.loads(_ARQ.read_text(encoding="utf-8"))
        return {}

    def _save(d: dict) -> None:
        _ARQ.write_text(json.dumps(d, indent=2), encoding="utf-8")

    def _impl_todos() -> dict:
        return {k: float(v) for k, v in _load().items()}

    def _impl_varios(mapa: dict) -> None:
        d = _load()
        for item_id, custo in mapa.items():
            if custo is None:
                d.pop(item_id, None)
            else:
                d[item_id] = float(custo)
        _save(d)


def custos() -> dict:
    """Mapa {item_id: custo} com cache curto."""
    if _cache["val"] is None or time.time() - _cache["ts"] > _TTL:
        _cache["val"] = _impl_todos()
        _cache["ts"] = time.time()
    return _cache["val"]


def custo_de(item_id: str) -> float | None:
    return custos().get(str(item_id))


def definir_varios(mapa: dict) -> None:
    """Salva varios custos de uma vez. mapa: {item_id: custo_ou_None}."""
    _impl_varios({str(k): v for k, v in mapa.items()})
    _cache["ts"] = 0.0
