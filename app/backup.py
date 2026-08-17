"""Backup e restauracao dos dados do app.

Exporta um JSON com os dados que voce criou (custos de produtos, fluxos,
atendente por pedido, usuarios, categorias, custos fixos, consumo de IA e
configuracoes como base de conhecimento/empresa). NAO inclui os tokens de
acesso do Mercado Livre/Bling (sensiveis e recuperaveis reconectando as contas).

No banco (DATABASE_URL) faz dump/restore das tabelas. Em arquivo local, dos .json.
"""
import json
import os

from . import config

DATABASE_URL = os.getenv("DATABASE_URL", "")

# tabelas do app + PK (ordem respeita as chaves estrangeiras: pai antes do filho)
_TABELAS = [
    ("fluxos", "id"),
    ("pedido_fluxo", "pack"),
    ("categorias", "id"),
    ("conversa_categoria", "pack"),
    ("produto_custo", "item_id"),
    ("pedido_atendente", "pack"),
    ("usuarios", "id"),
    ("custos_fixos", "id"),
    ("ia_consumo", "id"),
    ("nota_fiscal", "ref"),
    ("cliente", "id"),
    ("produto_balcao", "id"),
    ("pedido_balcao", "id"),
]


def _token_config(chave: str) -> bool:
    """True para chaves de configuracao (backup) e False para tokens de acesso."""
    return not (chave == "bling" or chave.startswith("ml:"))


if DATABASE_URL:
    import psycopg2
    from psycopg2.extras import RealDictCursor

    def _conn():
        return psycopg2.connect(DATABASE_URL)

    def exportar() -> dict:
        dump: dict = {"versao": 1, "tabelas": {}, "tokens": []}
        with _conn() as c, c.cursor(cursor_factory=RealDictCursor) as cur:
            for tab, _pk in _TABELAS:
                try:
                    cur.execute(f"SELECT * FROM {tab}")
                    dump["tabelas"][tab] = [dict(r) for r in cur.fetchall()]
                except Exception:
                    dump["tabelas"][tab] = []
            try:
                cur.execute("SELECT chave, dados FROM tokens")
                dump["tokens"] = [dict(r) for r in cur.fetchall() if _token_config(r["chave"])]
            except Exception:
                dump["tokens"] = []
        return dump

    def importar(dump: dict) -> None:
        with _conn() as c, c.cursor() as cur:
            for tab, pk in _TABELAS:
                for row in (dump.get("tabelas") or {}).get(tab) or []:
                    cols = list(row.keys())
                    colnames = ",".join(cols)
                    ph = ",".join(["%s"] * len(cols))
                    upd = ",".join(f"{k}=EXCLUDED.{k}" for k in cols if k != pk)
                    if upd:
                        sql = (f"INSERT INTO {tab} ({colnames}) VALUES ({ph}) "
                               f"ON CONFLICT ({pk}) DO UPDATE SET {upd}")
                    else:
                        sql = (f"INSERT INTO {tab} ({colnames}) VALUES ({ph}) "
                               f"ON CONFLICT ({pk}) DO NOTHING")
                    cur.execute(sql, [row[k] for k in cols])
            for row in (dump.get("tokens") or []):
                if _token_config(row.get("chave", "")):
                    d = row.get("dados")
                    cur.execute("INSERT INTO tokens (chave, dados) VALUES (%s,%s) "
                                "ON CONFLICT (chave) DO UPDATE SET dados = EXCLUDED.dados",
                                (row["chave"], json.dumps(d) if not isinstance(d, str) else d))
            # ajusta as sequences dos ids apos inserir com id explicito
            for tab, pk in _TABELAS:
                if pk == "id":
                    try:
                        cur.execute(f"SELECT setval(pg_get_serial_sequence('{tab}','id'), "
                                    f"COALESCE((SELECT MAX(id) FROM {tab}), 1))")
                    except Exception:
                        pass
            c.commit()

else:

    def exportar() -> dict:
        dump: dict = {"versao": 1, "arquivos": {}}
        nomes = ["produtos_custo.json", "fluxos.json", "categorias.json",
                 "usuarios.json", "custos_fixos.json", "ia_consumo.json",
                 "notas_fiscais.json", "clientes.json", "produtos_balcao.json",
                 "pedidos_balcao.json"]
        # + arquivos de configuracao do store (token_*.json), menos tokens de acesso
        for p in config.BASE_DIR.glob("token_*.json"):
            if p.name != "token.json" and not p.name.startswith("token_ml_"):
                nomes.append(p.name)
        for nome in nomes:
            p = config.BASE_DIR / nome
            if p.exists():
                try:
                    dump["arquivos"][nome] = json.loads(p.read_text(encoding="utf-8"))
                except Exception:
                    pass
        return dump

    def importar(dump: dict) -> None:
        for nome, conteudo in (dump.get("arquivos") or {}).items():
            if nome.startswith("token_ml_") or nome == "token.json":
                continue
            (config.BASE_DIR / nome).write_text(json.dumps(conteudo, indent=2), encoding="utf-8")
