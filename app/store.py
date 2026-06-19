"""Armazenamento dos tokens.

Regra:
  - Se existir a variavel DATABASE_URL (ambiente de nuvem) -> guarda no Postgres.
  - Senao (maquina local) -> guarda em arquivos JSON, como antes.

Assim o mesmo codigo roda local (arquivos) e no Render (banco persistente).
"""
import json
import os

from . import config

DATABASE_URL = os.getenv("DATABASE_URL", "")

# mapeia a "chave" logica para o arquivo local correspondente (modo fallback)
_ARQUIVOS = {
    "bling": config.TOKEN_FILE,
    "ml": config.TOKEN_FILE_ML,
}


if DATABASE_URL:
    import psycopg2

    def _conn():
        # A connection string do Neon ja inclui ?sslmode=require.
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

else:

    def salvar(chave: str, data: dict) -> None:
        _ARQUIVOS[chave].write_text(json.dumps(data, indent=2), encoding="utf-8")

    def carregar(chave: str) -> dict | None:
        arq = _ARQUIVOS[chave]
        if not arq.exists():
            return None
        return json.loads(arq.read_text(encoding="utf-8"))
