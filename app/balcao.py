"""Venda no balcao: cadastro de clientes e de produtos avulsos para emitir NF.

Diferente da aba Produtos (que espelha os anuncios do Mercado Livre), aqui os
produtos e clientes sao cadastrados a mao, para vendas fora do marketplace
(balcao). A emissao da NF usa o mesmo provedor Focus NFe (app/nfe.py).

Banco na nuvem (DATABASE_URL) ou arquivo local (clientes.json / produtos_balcao.json).
"""
import json
import os

from . import config

DATABASE_URL = os.getenv("DATABASE_URL", "")
_ARQ_CLI = config.BASE_DIR / "clientes.json"
_ARQ_PROD = config.BASE_DIR / "produtos_balcao.json"

_CAMPOS_CLI = ("nome", "doc_tipo", "doc_numero", "ie", "email", "telefone",
               "cep", "rua", "numero", "complemento", "bairro", "cidade", "uf")
_CAMPOS_PROD = ("nome", "ncm", "cfop", "cst", "origem", "unidade", "preco")


if DATABASE_URL:
    import psycopg2

    def _conn():
        return psycopg2.connect(DATABASE_URL)

    def _ddl(sql: str) -> None:
        try:
            with _conn() as c, c.cursor() as cur:
                cur.execute(sql)
                c.commit()
        except Exception:
            pass

    def _init() -> None:
        _ddl("CREATE TABLE IF NOT EXISTS cliente (id SERIAL PRIMARY KEY, nome TEXT, "
             "doc_tipo TEXT, doc_numero TEXT, ie TEXT, email TEXT, telefone TEXT, "
             "cep TEXT, rua TEXT, numero TEXT, complemento TEXT, bairro TEXT, "
             "cidade TEXT, uf TEXT)")
        _ddl("CREATE TABLE IF NOT EXISTS produto_balcao (id SERIAL PRIMARY KEY, nome TEXT, "
             "ncm TEXT, cfop TEXT, cst TEXT, origem TEXT, unidade TEXT, "
             "preco DOUBLE PRECISION)")

    _init()

    def _listar(tab: str, campos: tuple) -> list[dict]:
        cols = ",".join(("id",) + campos)
        with _conn() as c, c.cursor() as cur:
            cur.execute(f"SELECT {cols} FROM {tab} ORDER BY nome")
            return [dict(zip(("id",) + campos, r)) for r in cur.fetchall()]

    def _obter(tab: str, campos: tuple, oid: int) -> dict | None:
        cols = ",".join(("id",) + campos)
        with _conn() as c, c.cursor() as cur:
            cur.execute(f"SELECT {cols} FROM {tab} WHERE id=%s", (oid,))
            r = cur.fetchone()
        return dict(zip(("id",) + campos, r)) if r else None

    def _salvar(tab: str, campos: tuple, dados: dict) -> int:
        vals = [dados.get(c) for c in campos]
        oid = dados.get("id")
        with _conn() as c, c.cursor() as cur:
            if oid:
                sets = ",".join(f"{k}=%s" for k in campos)
                cur.execute(f"UPDATE {tab} SET {sets} WHERE id=%s", vals + [oid])
                novo = int(oid)
            else:
                colnames = ",".join(campos)
                ph = ",".join(["%s"] * len(campos))
                cur.execute(f"INSERT INTO {tab} ({colnames}) VALUES ({ph}) RETURNING id", vals)
                novo = cur.fetchone()[0]
            c.commit()
        return novo

    def _excluir(tab: str, oid: int) -> None:
        with _conn() as c, c.cursor() as cur:
            cur.execute(f"DELETE FROM {tab} WHERE id=%s", (oid,))
            c.commit()

else:

    def _load(arq) -> dict:
        if arq.exists():
            return json.loads(arq.read_text(encoding="utf-8"))
        return {"seq": 0, "itens": []}

    def _save(arq, d: dict) -> None:
        arq.write_text(json.dumps(d, indent=2), encoding="utf-8")

    def _arq(tab: str):
        return _ARQ_CLI if tab == "cliente" else _ARQ_PROD

    def _listar(tab: str, campos: tuple) -> list[dict]:
        return sorted(_load(_arq(tab))["itens"], key=lambda x: (x.get("nome") or "").lower())

    def _obter(tab: str, campos: tuple, oid: int) -> dict | None:
        return next((x for x in _load(_arq(tab))["itens"] if x["id"] == int(oid)), None)

    def _salvar(tab: str, campos: tuple, dados: dict) -> int:
        arq = _arq(tab)
        d = _load(arq)
        oid = dados.get("id")
        if oid:
            for x in d["itens"]:
                if x["id"] == int(oid):
                    x.update({k: dados.get(k) for k in campos})
                    _save(arq, d)
                    return int(oid)
        d["seq"] += 1
        reg = {"id": d["seq"], **{k: dados.get(k) for k in campos}}
        d["itens"].append(reg)
        _save(arq, d)
        return d["seq"]

    def _excluir(tab: str, oid: int) -> None:
        arq = _arq(tab)
        d = _load(arq)
        d["itens"] = [x for x in d["itens"] if x["id"] != int(oid)]
        _save(arq, d)


# --------------------------------------------------------------------------- #
# API do modulo
# --------------------------------------------------------------------------- #
def listar_clientes() -> list[dict]:
    return _listar("cliente", _CAMPOS_CLI)


def obter_cliente(cid: int) -> dict | None:
    return _obter("cliente", _CAMPOS_CLI, cid)


def salvar_cliente(dados: dict) -> int:
    return _salvar("cliente", _CAMPOS_CLI, dados)


def excluir_cliente(cid: int) -> None:
    _excluir("cliente", cid)


def listar_produtos() -> list[dict]:
    return _listar("produto_balcao", _CAMPOS_PROD)


def obter_produto(pid: int) -> dict | None:
    return _obter("produto_balcao", _CAMPOS_PROD, pid)


def salvar_produto(dados: dict) -> int:
    return _salvar("produto_balcao", _CAMPOS_PROD, dados)


def excluir_produto(pid: int) -> None:
    _excluir("produto_balcao", pid)
