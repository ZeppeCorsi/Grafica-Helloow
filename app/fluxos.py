"""Fluxo de atendimento e atendente responsavel por pedido (marca por 'pack').

- fluxos: lista editavel de etapas (ex.: "Aguardando arte", "Em producao",
  "Enviado"). O admin cria/renomeia/exclui, igual as categorias.
- pedido_fluxo: qual fluxo esta marcado em cada pedido (por pack).
- pedido_atendente: qual atendente (usuario da equipe) responde o pedido.

Banco na nuvem (DATABASE_URL) ou arquivo local, com cache em memoria (TTL).
"""
import json
import os
import time

from . import config

DATABASE_URL = os.getenv("DATABASE_URL", "")
_ARQ = config.BASE_DIR / "fluxos.json"


# --------------------------------------------------------------------------- #
# Armazenamento (banco OU arquivo)
# --------------------------------------------------------------------------- #
if DATABASE_URL:
    import psycopg2

    def _conn():
        return psycopg2.connect(DATABASE_URL)

    def _init() -> None:
        with _conn() as c, c.cursor() as cur:
            cur.execute("CREATE TABLE IF NOT EXISTS fluxos ("
                        "id SERIAL PRIMARY KEY, nome TEXT NOT NULL)")
            cur.execute("CREATE TABLE IF NOT EXISTS pedido_fluxo ("
                        "pack TEXT PRIMARY KEY, "
                        "fluxo_id INTEGER REFERENCES fluxos(id) ON DELETE CASCADE)")
            cur.execute("CREATE TABLE IF NOT EXISTS pedido_atendente ("
                        "pack TEXT PRIMARY KEY, atendente TEXT)")
            c.commit()

    _init()

    def _impl_listar_fluxos() -> list[dict]:
        with _conn() as c, c.cursor() as cur:
            cur.execute("SELECT id, nome FROM fluxos ORDER BY id")
            return [{"id": r[0], "nome": r[1]} for r in cur.fetchall()]

    def _impl_fluxo_marcas() -> dict:
        with _conn() as c, c.cursor() as cur:
            cur.execute("SELECT pack, fluxo_id FROM pedido_fluxo")
            return {r[0]: r[1] for r in cur.fetchall()}

    def _impl_atend_marcas() -> dict:
        with _conn() as c, c.cursor() as cur:
            cur.execute("SELECT pack, atendente FROM pedido_atendente")
            return {r[0]: r[1] for r in cur.fetchall()}

    def _impl_criar(nome: str) -> None:
        with _conn() as c, c.cursor() as cur:
            cur.execute("INSERT INTO fluxos (nome) VALUES (%s)", (nome,))
            c.commit()

    def _impl_renomear(fid: int, nome: str) -> None:
        with _conn() as c, c.cursor() as cur:
            cur.execute("UPDATE fluxos SET nome = %s WHERE id = %s", (nome, fid))
            c.commit()

    def _impl_excluir(fid: int) -> None:
        with _conn() as c, c.cursor() as cur:
            cur.execute("DELETE FROM fluxos WHERE id = %s", (fid,))
            c.commit()

    def _impl_marcar_fluxo(pack: str, fid: int | None) -> None:
        with _conn() as c, c.cursor() as cur:
            if fid:
                cur.execute("INSERT INTO pedido_fluxo (pack, fluxo_id) VALUES (%s, %s) "
                            "ON CONFLICT (pack) DO UPDATE SET fluxo_id = EXCLUDED.fluxo_id",
                            (pack, fid))
            else:
                cur.execute("DELETE FROM pedido_fluxo WHERE pack = %s", (pack,))
            c.commit()

    def _impl_definir_atendente(pack: str, atendente: str) -> None:
        with _conn() as c, c.cursor() as cur:
            if atendente:
                cur.execute("INSERT INTO pedido_atendente (pack, atendente) VALUES (%s, %s) "
                            "ON CONFLICT (pack) DO UPDATE SET atendente = EXCLUDED.atendente",
                            (pack, atendente))
            else:
                cur.execute("DELETE FROM pedido_atendente WHERE pack = %s", (pack,))
            c.commit()

else:

    def _load() -> dict:
        if _ARQ.exists():
            return json.loads(_ARQ.read_text(encoding="utf-8"))
        return {"seq": 0, "fluxos": [], "fluxo_marcas": {}, "atend_marcas": {}}

    def _save(d: dict) -> None:
        _ARQ.write_text(json.dumps(d, indent=2), encoding="utf-8")

    def _impl_listar_fluxos() -> list[dict]:
        return list(_load()["fluxos"])

    def _impl_fluxo_marcas() -> dict:
        return dict(_load()["fluxo_marcas"])

    def _impl_atend_marcas() -> dict:
        return dict(_load()["atend_marcas"])

    def _impl_criar(nome: str) -> None:
        d = _load()
        d["seq"] += 1
        d["fluxos"].append({"id": d["seq"], "nome": nome})
        _save(d)

    def _impl_renomear(fid: int, nome: str) -> None:
        d = _load()
        for f in d["fluxos"]:
            if f["id"] == fid:
                f["nome"] = nome
        _save(d)

    def _impl_excluir(fid: int) -> None:
        d = _load()
        d["fluxos"] = [f for f in d["fluxos"] if f["id"] != fid]
        d["fluxo_marcas"] = {k: v for k, v in d["fluxo_marcas"].items() if v != fid}
        _save(d)

    def _impl_marcar_fluxo(pack: str, fid: int | None) -> None:
        d = _load()
        if fid:
            d["fluxo_marcas"][pack] = fid
        else:
            d["fluxo_marcas"].pop(pack, None)
        _save(d)

    def _impl_definir_atendente(pack: str, atendente: str) -> None:
        d = _load()
        if atendente:
            d["atend_marcas"][pack] = atendente
        else:
            d["atend_marcas"].pop(pack, None)
        _save(d)


# --------------------------------------------------------------------------- #
# Cache (TTL) + API do modulo
# --------------------------------------------------------------------------- #
_TTL = 30
_cache: dict = {"fluxos": None, "fluxos_ts": 0.0, "fm": None, "fm_ts": 0.0,
                "am": None, "am_ts": 0.0}


def _invalidar() -> None:
    _cache["fluxos_ts"] = 0.0
    _cache["fm_ts"] = 0.0
    _cache["am_ts"] = 0.0


def listar_fluxos() -> list[dict]:
    if _cache["fluxos"] is None or time.time() - _cache["fluxos_ts"] > _TTL:
        _cache["fluxos"] = _impl_listar_fluxos()
        _cache["fluxos_ts"] = time.time()
    return _cache["fluxos"]


def fluxo_marcas() -> dict:
    if _cache["fm"] is None or time.time() - _cache["fm_ts"] > _TTL:
        _cache["fm"] = _impl_fluxo_marcas()
        _cache["fm_ts"] = time.time()
    return _cache["fm"]


def atendente_marcas() -> dict:
    if _cache["am"] is None or time.time() - _cache["am_ts"] > _TTL:
        _cache["am"] = _impl_atend_marcas()
        _cache["am_ts"] = time.time()
    return _cache["am"]


def criar_fluxo(nome: str) -> None:
    _impl_criar(nome)
    _invalidar()


def renomear_fluxo(fid: int, nome: str) -> None:
    _impl_renomear(fid, nome)
    _invalidar()


def excluir_fluxo(fid: int) -> None:
    _impl_excluir(fid)
    _invalidar()


def marcar_fluxo(pack: str, fid: int | None) -> None:
    _impl_marcar_fluxo(pack, fid)
    _invalidar()


def definir_atendente(pack: str, atendente: str) -> None:
    _impl_definir_atendente(pack, atendente)
    _invalidar()
