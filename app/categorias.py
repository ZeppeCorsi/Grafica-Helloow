"""Categorias (etiquetas) das conversas.

Guarda apenas a MARCA (qual categoria) de cada conversa - nao guarda as
mensagens. A conversa continua vindo ao vivo do Mercado Livre; aqui so
sobrepomos a etiqueta. Banco na nuvem (DATABASE_URL) ou arquivo local.
"""
import json
import os

from . import config

DATABASE_URL = os.getenv("DATABASE_URL", "")
_ARQ = config.BASE_DIR / "categorias.json"


if DATABASE_URL:
    import psycopg2

    def _conn():
        return psycopg2.connect(DATABASE_URL)

    def _init() -> None:
        with _conn() as c, c.cursor() as cur:
            cur.execute("CREATE TABLE IF NOT EXISTS categorias ("
                        "id SERIAL PRIMARY KEY, nome TEXT NOT NULL)")
            cur.execute("CREATE TABLE IF NOT EXISTS conversa_categoria ("
                        "pack TEXT PRIMARY KEY, "
                        "categoria_id INTEGER REFERENCES categorias(id) ON DELETE CASCADE)")
            c.commit()

    _init()

    def listar_categorias() -> list[dict]:
        with _conn() as c, c.cursor() as cur:
            cur.execute("SELECT id, nome FROM categorias ORDER BY nome")
            return [{"id": r[0], "nome": r[1]} for r in cur.fetchall()]

    def criar_categoria(nome: str) -> None:
        with _conn() as c, c.cursor() as cur:
            cur.execute("INSERT INTO categorias (nome) VALUES (%s)", (nome,))
            c.commit()

    def renomear_categoria(cid: int, nome: str) -> None:
        with _conn() as c, c.cursor() as cur:
            cur.execute("UPDATE categorias SET nome = %s WHERE id = %s", (nome, cid))
            c.commit()

    def excluir_categoria(cid: int) -> None:
        with _conn() as c, c.cursor() as cur:
            cur.execute("DELETE FROM categorias WHERE id = %s", (cid,))
            c.commit()

    def marcar(pack: str, cid: int | None) -> None:
        with _conn() as c, c.cursor() as cur:
            if cid:
                cur.execute("INSERT INTO conversa_categoria (pack, categoria_id) VALUES (%s, %s) "
                            "ON CONFLICT (pack) DO UPDATE SET categoria_id = EXCLUDED.categoria_id",
                            (pack, cid))
            else:
                cur.execute("DELETE FROM conversa_categoria WHERE pack = %s", (pack,))
            c.commit()

    def marcas() -> dict:
        with _conn() as c, c.cursor() as cur:
            cur.execute("SELECT pack, categoria_id FROM conversa_categoria")
            return {r[0]: r[1] for r in cur.fetchall()}

else:

    def _load() -> dict:
        if _ARQ.exists():
            return json.loads(_ARQ.read_text(encoding="utf-8"))
        return {"seq": 0, "categorias": [], "marcas": {}}

    def _save(d: dict) -> None:
        _ARQ.write_text(json.dumps(d, indent=2), encoding="utf-8")

    def listar_categorias() -> list[dict]:
        return sorted(_load()["categorias"], key=lambda x: x["nome"].lower())

    def criar_categoria(nome: str) -> None:
        d = _load()
        d["seq"] += 1
        d["categorias"].append({"id": d["seq"], "nome": nome})
        _save(d)

    def renomear_categoria(cid: int, nome: str) -> None:
        d = _load()
        for c in d["categorias"]:
            if c["id"] == cid:
                c["nome"] = nome
        _save(d)

    def excluir_categoria(cid: int) -> None:
        d = _load()
        d["categorias"] = [c for c in d["categorias"] if c["id"] != cid]
        d["marcas"] = {k: v for k, v in d["marcas"].items() if v != cid}
        _save(d)

    def marcar(pack: str, cid: int | None) -> None:
        d = _load()
        if cid:
            d["marcas"][pack] = cid
        else:
            d["marcas"].pop(pack, None)
        _save(d)

    def marcas() -> dict:
        return dict(_load()["marcas"])
