"""Categorias (etiquetas) das conversas.

Guarda apenas a MARCA (qual categoria) de cada conversa - nao guarda as
mensagens. Banco na nuvem (DATABASE_URL) ou arquivo local. Tem cache em
memoria (TTL) para evitar idas repetidas ao banco a cada tela.
"""
import json
import os
import time

from . import config

DATABASE_URL = os.getenv("DATABASE_URL", "")
_ARQ = config.BASE_DIR / "categorias.json"


# --------------------------------------------------------------------------- #
# Armazenamento (banco OU arquivo)
# --------------------------------------------------------------------------- #
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

    def _impl_listar() -> list[dict]:
        with _conn() as c, c.cursor() as cur:
            cur.execute("SELECT id, nome FROM categorias ORDER BY nome")
            return [{"id": r[0], "nome": r[1]} for r in cur.fetchall()]

    def _impl_marcas() -> dict:
        with _conn() as c, c.cursor() as cur:
            cur.execute("SELECT pack, categoria_id FROM conversa_categoria")
            return {r[0]: r[1] for r in cur.fetchall()}

    def _impl_criar(nome: str) -> None:
        with _conn() as c, c.cursor() as cur:
            cur.execute("INSERT INTO categorias (nome) VALUES (%s)", (nome,))
            c.commit()

    def _impl_renomear(cid: int, nome: str) -> None:
        with _conn() as c, c.cursor() as cur:
            cur.execute("UPDATE categorias SET nome = %s WHERE id = %s", (nome, cid))
            c.commit()

    def _impl_excluir(cid: int) -> None:
        with _conn() as c, c.cursor() as cur:
            cur.execute("DELETE FROM categorias WHERE id = %s", (cid,))
            c.commit()

    def _impl_marcar(pack: str, cid: int | None) -> None:
        with _conn() as c, c.cursor() as cur:
            if cid:
                cur.execute("INSERT INTO conversa_categoria (pack, categoria_id) VALUES (%s, %s) "
                            "ON CONFLICT (pack) DO UPDATE SET categoria_id = EXCLUDED.categoria_id",
                            (pack, cid))
            else:
                cur.execute("DELETE FROM conversa_categoria WHERE pack = %s", (pack,))
            c.commit()

else:

    def _load() -> dict:
        if _ARQ.exists():
            return json.loads(_ARQ.read_text(encoding="utf-8"))
        return {"seq": 0, "categorias": [], "marcas": {}}

    def _save(d: dict) -> None:
        _ARQ.write_text(json.dumps(d, indent=2), encoding="utf-8")

    def _impl_listar() -> list[dict]:
        return sorted(_load()["categorias"], key=lambda x: x["nome"].lower())

    def _impl_marcas() -> dict:
        return dict(_load()["marcas"])

    def _impl_criar(nome: str) -> None:
        d = _load()
        d["seq"] += 1
        d["categorias"].append({"id": d["seq"], "nome": nome})
        _save(d)

    def _impl_renomear(cid: int, nome: str) -> None:
        d = _load()
        for c in d["categorias"]:
            if c["id"] == cid:
                c["nome"] = nome
        _save(d)

    def _impl_excluir(cid: int) -> None:
        d = _load()
        d["categorias"] = [c for c in d["categorias"] if c["id"] != cid]
        d["marcas"] = {k: v for k, v in d["marcas"].items() if v != cid}
        _save(d)

    def _impl_marcar(pack: str, cid: int | None) -> None:
        d = _load()
        if cid:
            d["marcas"][pack] = cid
        else:
            d["marcas"].pop(pack, None)
        _save(d)


# --------------------------------------------------------------------------- #
# Camada de cache (TTL) - evita consultar o banco a cada tela
# --------------------------------------------------------------------------- #
_TTL = 30
_cache: dict = {"cats": None, "cats_ts": 0.0, "marcas": None, "marcas_ts": 0.0}


def _invalidar() -> None:
    _cache["cats_ts"] = 0.0
    _cache["marcas_ts"] = 0.0


def listar_categorias() -> list[dict]:
    if _cache["cats"] is None or time.time() - _cache["cats_ts"] > _TTL:
        _cache["cats"] = _impl_listar()
        _cache["cats_ts"] = time.time()
    return _cache["cats"]


def marcas() -> dict:
    if _cache["marcas"] is None or time.time() - _cache["marcas_ts"] > _TTL:
        _cache["marcas"] = _impl_marcas()
        _cache["marcas_ts"] = time.time()
    return _cache["marcas"]


def criar_categoria(nome: str) -> None:
    _impl_criar(nome)
    _invalidar()


def renomear_categoria(cid: int, nome: str) -> None:
    _impl_renomear(cid, nome)
    _invalidar()


def excluir_categoria(cid: int) -> None:
    _impl_excluir(cid)
    _invalidar()


def marcar(pack: str, cid: int | None) -> None:
    _impl_marcar(pack, cid)
    _invalidar()
