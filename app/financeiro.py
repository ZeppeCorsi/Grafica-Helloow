"""Custos fixos do mes (aluguel, salarios, embalagem fixa, software, etc.).

Usados no "Fechamento do mes": Lucro das vendas (aba Resultado) - custos fixos
- custo de IA = resultado final. Banco na nuvem (DATABASE_URL) ou arquivo local.
"""
import json
import os

from . import config

DATABASE_URL = os.getenv("DATABASE_URL", "")
_ARQ = config.BASE_DIR / "custos_fixos.json"


if DATABASE_URL:
    import psycopg2

    def _conn():
        return psycopg2.connect(DATABASE_URL)

    def _init() -> None:
        with _conn() as c, c.cursor() as cur:
            cur.execute("CREATE TABLE IF NOT EXISTS custos_fixos ("
                        "id SERIAL PRIMARY KEY, nome TEXT NOT NULL, "
                        "valor DOUBLE PRECISION NOT NULL DEFAULT 0)")
            c.commit()

    _init()

    def listar_custos() -> list[dict]:
        with _conn() as c, c.cursor() as cur:
            cur.execute("SELECT id, nome, valor FROM custos_fixos ORDER BY nome")
            return [{"id": r[0], "nome": r[1], "valor": float(r[2])} for r in cur.fetchall()]

    def adicionar_custo(nome: str, valor: float) -> None:
        with _conn() as c, c.cursor() as cur:
            cur.execute("INSERT INTO custos_fixos (nome, valor) VALUES (%s, %s)", (nome, valor))
            c.commit()

    def remover_custo(cid: int) -> None:
        with _conn() as c, c.cursor() as cur:
            cur.execute("DELETE FROM custos_fixos WHERE id = %s", (cid,))
            c.commit()

else:

    def _load() -> dict:
        if _ARQ.exists():
            return json.loads(_ARQ.read_text(encoding="utf-8"))
        return {"seq": 0, "custos": []}

    def _save(d: dict) -> None:
        _ARQ.write_text(json.dumps(d, indent=2), encoding="utf-8")

    def listar_custos() -> list[dict]:
        return sorted(_load()["custos"], key=lambda x: x["nome"].lower())

    def adicionar_custo(nome: str, valor: float) -> None:
        d = _load()
        d["seq"] += 1
        d["custos"].append({"id": d["seq"], "nome": nome, "valor": float(valor)})
        _save(d)

    def remover_custo(cid: int) -> None:
        d = _load()
        d["custos"] = [c for c in d["custos"] if c["id"] != cid]
        _save(d)


def total_custos() -> float:
    return sum(c["valor"] for c in listar_custos())
