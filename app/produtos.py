"""Custo de producao e dados fiscais de cada produto (anuncio do Mercado Livre).

O usuario preenche na aba Produtos:
  - o custo de producao (alimenta a margem nas abas Resultado e Financeiro);
  - os dados fiscais (NCM, CFOP, CST/CSOSN, origem, unidade) usados na emissao
    da Nota Fiscal (modulo nfe.py).

Tudo guardado por item_id do ML (ex.: 'MLB1234567890'). Banco na nuvem
(DATABASE_URL) ou arquivo local, com cache em memoria (TTL) para nao bater no
banco a cada pedido do Resultado/NF.
"""
import json
import os
import time

from . import config

DATABASE_URL = os.getenv("DATABASE_URL", "")
_ARQ = config.BASE_DIR / "produtos_custo.json"
_TTL = 60
_cache: dict = {"val": None, "ts": 0.0}

# campos fiscais guardados por produto (alem do custo)
_CAMPOS_FISCAIS = ("ncm", "cfop", "cst", "origem", "unidade")


if DATABASE_URL:
    import psycopg2

    def _conn():
        return psycopg2.connect(DATABASE_URL)

    def _ddl(sql: str) -> None:
        """Roda um DDL isolado (erro nao contamina outras transacoes)."""
        try:
            with _conn() as c, c.cursor() as cur:
                cur.execute(sql)
                c.commit()
        except Exception:
            pass

    def _init() -> None:
        _ddl("CREATE TABLE IF NOT EXISTS produto_custo ("
             "item_id TEXT PRIMARY KEY, custo DOUBLE PRECISION)")
        # colunas fiscais (adicionadas depois; nao quebram bases antigas)
        for col in _CAMPOS_FISCAIS:
            _ddl(f"ALTER TABLE produto_custo ADD COLUMN IF NOT EXISTS {col} TEXT")
        # bases antigas criaram custo como NOT NULL DEFAULT 0: soltamos isso para
        # permitir produto so-fiscal (custo NULL) sem virar custo 0 (margem errada).
        _ddl("ALTER TABLE produto_custo ALTER COLUMN custo DROP NOT NULL")
        _ddl("ALTER TABLE produto_custo ALTER COLUMN custo DROP DEFAULT")

    _init()

    def _impl_todos() -> dict:
        cols = ",".join(_CAMPOS_FISCAIS)
        with _conn() as c, c.cursor() as cur:
            cur.execute(f"SELECT item_id, custo, {cols} FROM produto_custo")
            out = {}
            for r in cur.fetchall():
                out[r[0]] = {
                    "custo": None if r[1] is None else float(r[1]),
                    **{campo: r[2 + i] for i, campo in enumerate(_CAMPOS_FISCAIS)},
                }
            return out

    def _impl_custos(mapa: dict) -> None:
        # Upsert do custo SEM apagar os dados fiscais da linha. Custo vazio vira NULL
        # (a linha continua existindo para preservar o fiscal).
        from psycopg2.extras import execute_values
        vals = [(item_id, custo) for item_id, custo in mapa.items()]
        with _conn() as c, c.cursor() as cur:
            if vals:
                execute_values(
                    cur,
                    "INSERT INTO produto_custo (item_id, custo) VALUES %s "
                    "ON CONFLICT (item_id) DO UPDATE SET custo = EXCLUDED.custo",
                    vals,
                )
            c.commit()

    def _impl_fiscal(mapa: dict) -> None:
        # mapa: {item_id: {ncm, cfop, cst, origem, unidade}}
        with _conn() as c, c.cursor() as cur:
            for item_id, dados in mapa.items():
                sets = ",".join(f"{campo} = %s" for campo in _CAMPOS_FISCAIS)
                cols = ",".join(_CAMPOS_FISCAIS)
                ph = ",".join(["%s"] * len(_CAMPOS_FISCAIS))
                valores = [dados.get(campo) or None for campo in _CAMPOS_FISCAIS]
                cur.execute(
                    f"INSERT INTO produto_custo (item_id, {cols}) VALUES (%s, {ph}) "
                    f"ON CONFLICT (item_id) DO UPDATE SET {sets}",
                    [item_id] + valores + valores,
                )
            c.commit()

else:

    def _load() -> dict:
        if not _ARQ.exists():
            return {}
        d = json.loads(_ARQ.read_text(encoding="utf-8"))
        # migracao: formato antigo era {item_id: custo(float)}
        out = {}
        for k, v in d.items():
            if isinstance(v, dict):
                out[k] = v
            else:
                out[k] = {"custo": float(v)}
        return out

    def _save(d: dict) -> None:
        _ARQ.write_text(json.dumps(d, indent=2), encoding="utf-8")

    def _impl_todos() -> dict:
        out = {}
        for k, v in _load().items():
            reg = {"custo": None if v.get("custo") is None else float(v["custo"])}
            for campo in _CAMPOS_FISCAIS:
                reg[campo] = v.get(campo)
            out[k] = reg
        return out

    def _impl_custos(mapa: dict) -> None:
        d = _load()
        for item_id, custo in mapa.items():
            reg = d.setdefault(item_id, {})
            reg["custo"] = None if custo is None else float(custo)
        _save(d)

    def _impl_fiscal(mapa: dict) -> None:
        d = _load()
        for item_id, dados in mapa.items():
            reg = d.setdefault(item_id, {})
            for campo in _CAMPOS_FISCAIS:
                reg[campo] = dados.get(campo) or None
        _save(d)


def _todos() -> dict:
    """Mapa {item_id: {custo, ncm, cfop, cst, origem, unidade}} com cache curto."""
    if _cache["val"] is None or time.time() - _cache["ts"] > _TTL:
        _cache["val"] = _impl_todos()
        _cache["ts"] = time.time()
    return _cache["val"]


def custos() -> dict:
    """Mapa {item_id: custo} (so os que tem custo preenchido)."""
    return {k: v["custo"] for k, v in _todos().items() if v.get("custo") is not None}


def custo_de(item_id: str) -> float | None:
    reg = _todos().get(str(item_id))
    return reg.get("custo") if reg else None


def fiscal() -> dict:
    """Mapa {item_id: {ncm, cfop, cst, origem, unidade}} (so campos preenchidos)."""
    out = {}
    for k, v in _todos().items():
        campos = {c: v.get(c) for c in _CAMPOS_FISCAIS if v.get(c)}
        if campos:
            out[k] = campos
    return out


def fiscal_de(item_id: str) -> dict:
    reg = _todos().get(str(item_id)) or {}
    return {c: reg.get(c) for c in _CAMPOS_FISCAIS}


def definir_varios(mapa: dict) -> None:
    """Salva varios custos de uma vez. mapa: {item_id: custo_ou_None}."""
    _impl_custos({str(k): v for k, v in mapa.items()})
    _cache["ts"] = 0.0


def definir_fiscal_varios(mapa: dict) -> None:
    """Salva os dados fiscais de varios produtos. mapa: {item_id: {ncm, cfop, ...}}."""
    limpo = {str(k): {c: (dados.get(c) or "").strip() for c in _CAMPOS_FISCAIS}
             for k, dados in mapa.items()}
    _impl_fiscal(limpo)
    _cache["ts"] = 0.0
