"""Usuarios da equipe (admin + atendentes) e log de atividade.

Senhas guardadas com hash (pbkdf2). Banco na nuvem (DATABASE_URL) ou arquivo
local. O usuario "mestre" (APP_USER/APP_PASSWORD) continua valendo sempre como
admin, mesmo que a tabela esteja vazia (rede de seguranca para nao travar fora).
"""
import hashlib
import json
import os
import secrets
import time
from datetime import datetime

from . import config

DATABASE_URL = os.getenv("DATABASE_URL", "")
_ARQ = config.BASE_DIR / "usuarios.json"


def _hash(senha: str, salt: str | None = None) -> str:
    salt = salt or secrets.token_hex(8)
    h = hashlib.pbkdf2_hmac("sha256", senha.encode(), salt.encode(), 100_000).hex()
    return f"{salt}${h}"


def _verifica(senha: str, armazenado: str) -> bool:
    try:
        salt = armazenado.split("$", 1)[0]
    except Exception:
        return False
    return secrets.compare_digest(_hash(senha, salt), armazenado)


if DATABASE_URL:
    import psycopg2

    def _conn():
        return psycopg2.connect(DATABASE_URL)

    def _init() -> None:
        with _conn() as c, c.cursor() as cur:
            cur.execute("CREATE TABLE IF NOT EXISTS usuarios ("
                        "id SERIAL PRIMARY KEY, nome TEXT, usuario TEXT UNIQUE, "
                        "senha TEXT, papel TEXT DEFAULT 'atendente', ativo BOOLEAN DEFAULT TRUE)")
            cur.execute("CREATE TABLE IF NOT EXISTS log_atividade ("
                        "id SERIAL PRIMARY KEY, ts TIMESTAMPTZ DEFAULT now(), "
                        "usuario TEXT, acao TEXT, alvo TEXT)")
            c.commit()

    _init()

    def listar_usuarios() -> list[dict]:
        with _conn() as c, c.cursor() as cur:
            cur.execute("SELECT id, nome, usuario, papel, ativo FROM usuarios ORDER BY nome")
            return [{"id": r[0], "nome": r[1], "usuario": r[2], "papel": r[3], "ativo": r[4]}
                    for r in cur.fetchall()]

    def criar_usuario(nome: str, usuario: str, senha: str, papel: str) -> None:
        with _conn() as c, c.cursor() as cur:
            cur.execute("INSERT INTO usuarios (nome, usuario, senha, papel) VALUES (%s,%s,%s,%s) "
                        "ON CONFLICT (usuario) DO UPDATE SET nome=EXCLUDED.nome, "
                        "senha=EXCLUDED.senha, papel=EXCLUDED.papel, ativo=TRUE",
                        (nome, usuario, _hash(senha), papel))
            c.commit()

    def excluir_usuario(uid: int) -> None:
        with _conn() as c, c.cursor() as cur:
            cur.execute("DELETE FROM usuarios WHERE id=%s", (uid,))
            c.commit()

    def autenticar(usuario: str, senha: str) -> dict | None:
        try:
            with _conn() as c, c.cursor() as cur:
                cur.execute("SELECT nome, senha, papel FROM usuarios "
                            "WHERE usuario=%s AND ativo=TRUE", (usuario,))
                row = cur.fetchone()
        except Exception:
            return None
        if row and _verifica(senha, row[1]):
            return {"nome": row[0], "papel": row[2]}
        return None

    def registrar(usuario: str, acao: str, alvo: str) -> None:
        try:
            with _conn() as c, c.cursor() as cur:
                cur.execute("INSERT INTO log_atividade (usuario, acao, alvo) VALUES (%s,%s,%s)",
                            (usuario, acao, alvo))
                c.commit()
        except Exception:
            pass

    def listar_log(limite: int = 200) -> list[dict]:
        with _conn() as c, c.cursor() as cur:
            cur.execute("SELECT ts, usuario, acao, alvo FROM log_atividade "
                        "ORDER BY ts DESC LIMIT %s", (limite,))
            return [{"ts": r[0], "usuario": r[1], "acao": r[2], "alvo": r[3]}
                    for r in cur.fetchall()]

    def resumo() -> list[dict]:
        with _conn() as c, c.cursor() as cur:
            cur.execute("SELECT usuario, COUNT(*) FROM log_atividade GROUP BY usuario "
                        "ORDER BY COUNT(*) DESC")
            return [{"usuario": r[0], "total": r[1]} for r in cur.fetchall()]

else:

    def _load() -> dict:
        if _ARQ.exists():
            return json.loads(_ARQ.read_text(encoding="utf-8"))
        return {"seq": 0, "usuarios": [], "log": []}

    def _save(d: dict) -> None:
        _ARQ.write_text(json.dumps(d, indent=2), encoding="utf-8")

    def listar_usuarios() -> list[dict]:
        return [{k: u[k] for k in ("id", "nome", "usuario", "papel", "ativo")}
                for u in _load()["usuarios"]]

    def criar_usuario(nome: str, usuario: str, senha: str, papel: str) -> None:
        d = _load()
        for u in d["usuarios"]:
            if u["usuario"] == usuario:
                u.update(nome=nome, senha=_hash(senha), papel=papel, ativo=True)
                _save(d)
                return
        d["seq"] += 1
        d["usuarios"].append({"id": d["seq"], "nome": nome, "usuario": usuario,
                              "senha": _hash(senha), "papel": papel, "ativo": True})
        _save(d)

    def excluir_usuario(uid: int) -> None:
        d = _load()
        d["usuarios"] = [u for u in d["usuarios"] if u["id"] != uid]
        _save(d)

    def autenticar(usuario: str, senha: str) -> dict | None:
        for u in _load()["usuarios"]:
            if u["usuario"] == usuario and u.get("ativo", True) and _verifica(senha, u["senha"]):
                return {"nome": u["nome"], "papel": u["papel"]}
        return None

    def registrar(usuario: str, acao: str, alvo: str) -> None:
        d = _load()
        d["log"].insert(0, {"ts": time.time(), "usuario": usuario, "acao": acao, "alvo": alvo})
        d["log"] = d["log"][:500]
        _save(d)

    def listar_log(limite: int = 200) -> list[dict]:
        out = []
        for r in _load()["log"][:limite]:
            out.append({"ts": datetime.fromtimestamp(r["ts"]), "usuario": r["usuario"],
                        "acao": r["acao"], "alvo": r["alvo"]})
        return out

    def resumo() -> list[dict]:
        cont: dict = {}
        for r in _load()["log"]:
            cont[r["usuario"]] = cont.get(r["usuario"], 0) + 1
        return [{"usuario": k, "total": v}
                for k, v in sorted(cont.items(), key=lambda x: -x[1])]
