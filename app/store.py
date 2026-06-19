"""Armazenamento dos tokens.

Regra:
  - Se existir DATABASE_URL (nuvem) -> guarda no Postgres.
  - Senao (local) -> guarda em arquivos JSON.

Chaves: "bling", "ml" (legado) e "ml:{user_id}" (uma por conta do Mercado Livre).
"""
import json
import os

from . import config

DATABASE_URL = os.getenv("DATABASE_URL", "")


def _arquivo(chave: str):
    if chave == "bling":
        return config.TOKEN_FILE
    if chave == "ml":
        return config.TOKEN_FILE_ML
    return config.BASE_DIR / ("token_" + chave.replace(":", "_") + ".json")


if DATABASE_URL:
    import psycopg2

    def _conn():
        return psycopg2.connect(DATABASE_URL)

    def _init() -> None:
        with _conn() as c, c.cursor() as cur:
            cur.execute(
                "CREATE TABLE IF NOT EXISTS tokens ("
                "chave TEXT PRIMARY KEY, dados JSONB NOT NULL)"
            )
            c.commit()

    _init()

    def salvar(chave: str, data: dict) -> None:
        with _conn() as c, c.cursor() as cur:
            cur.execute(
                "INSERT INTO tokens (chave, dados) VALUES (%s, %s) "
                "ON CONFLICT (chave) DO UPDATE SET dados = EXCLUDED.dados",
                (chave, json.dumps(data)),
            )
            c.commit()

    def carregar(chave: str) -> dict | None:
        with _conn() as c, c.cursor() as cur:
            cur.execute("SELECT dados FROM tokens WHERE chave = %s", (chave,))
            row = cur.fetchone()
            return row[0] if row else None

    def listar(prefixo: str) -> list[dict]:
        with _conn() as c, c.cursor() as cur:
            cur.execute("SELECT dados FROM tokens WHERE chave LIKE %s ORDER BY chave", (prefixo + "%",))
            return [r[0] for r in cur.fetchall()]

    def remover(chave: str) -> None:
        with _conn() as c, c.cursor() as cur:
            cur.execute("DELETE FROM tokens WHERE chave = %s", (chave,))
            c.commit()

else:

    def salvar(chave: str, data: dict) -> None:
        _arquivo(chave).write_text(json.dumps(data, indent=2), encoding="utf-8")

    def carregar(chave: str) -> dict | None:
        arq = _arquivo(chave)
        return json.loads(arq.read_text(encoding="utf-8")) if arq.exists() else None

    def listar(prefixo: str) -> list[dict]:
        res = []
        if prefixo == "ml:":
            for p in sorted(config.BASE_DIR.glob("token_ml_*.json")):
                res.append(json.loads(p.read_text(encoding="utf-8")))
        return res

    def remover(chave: str) -> None:
        arq = _arquivo(chave)
        if arq.exists():
            arq.unlink()
