"""Emissao de Nota Fiscal Eletronica (NF-e) via provedor Focus NFe.

Nao emitimos nota por conta propria (isso exige certificado digital + SEFAZ):
integramos um provedor fiscal. O Zappe Hub monta o payload a partir do pedido do
Mercado Livre e envia para o Focus NFe, que fala com a SEFAZ e devolve a nota
autorizada (XML + DANFE em PDF).

Configuracao por variaveis de ambiente (no Render), nunca no codigo:
  FOCUS_NFE_TOKEN      -> token da conta Focus (obrigatorio para emitir de verdade)
  FOCUS_NFE_AMBIENTE   -> "homologacao" (teste, padrao) ou "producao"
  FOCUS_NFE_CNPJ       -> CNPJ do emitente (empresa cadastrada no Focus, com certificado)

Enquanto FOCUS_NFE_TOKEN nao estiver setado, configurado() e False e a emissao
fica desligada (modo simulacao/preparacao), igual fizemos com a IA.

Guarda o resultado de cada emissao por pedido (pack) no banco (DATABASE_URL) ou
em arquivo local. NUNCA guarda o certificado/senha do cliente.
"""
import json
import os
import time

import httpx

from . import config

DATABASE_URL = os.getenv("DATABASE_URL", "")
_ARQ = config.BASE_DIR / "notas_fiscais.json"

TOKEN = os.getenv("FOCUS_NFE_TOKEN", "")
AMBIENTE = os.getenv("FOCUS_NFE_AMBIENTE", "homologacao").strip().lower()
CNPJ_EMITENTE = os.getenv("FOCUS_NFE_CNPJ", "").strip()

_BASE = ("https://api.focusnfe.com.br" if AMBIENTE == "producao"
         else "https://homologacao.focusnfe.com.br")


def configurado() -> bool:
    """True quando ha token do Focus (emissao ligada). Senao, modo preparacao."""
    return bool(TOKEN)


def ambiente() -> str:
    return "producao" if AMBIENTE == "producao" else "homologacao"


# --------------------------------------------------------------------------- #
# Chamadas ao Focus NFe (auth basic: token como usuario, senha vazia)
# --------------------------------------------------------------------------- #
def _emitir_focus(ref: str, payload: dict) -> dict:
    resp = httpx.post(
        f"{_BASE}/v2/nfe",
        params={"ref": ref},
        json=payload,
        auth=(TOKEN, ""),
        timeout=60,
    )
    try:
        dados = resp.json()
    except Exception:
        dados = {"erro": "resposta_invalida", "mensagem": resp.text[:300]}
    dados["_http"] = resp.status_code
    return dados


def _consultar_focus(ref: str) -> dict:
    resp = httpx.get(f"{_BASE}/v2/nfe/{ref}", auth=(TOKEN, ""), timeout=30)
    try:
        dados = resp.json()
    except Exception:
        dados = {"status": "erro", "mensagem": resp.text[:300]}
    dados["_http"] = resp.status_code
    return dados


def _normaliza(ref: str, pack: str, conta: str, dados: dict) -> dict:
    """Extrai os campos que interessam da resposta do Focus para guardar/exibir."""
    status = dados.get("status") or ("erro" if dados.get("_http", 200) >= 400 else "processando")
    danfe = dados.get("caminho_danfe") or ""
    xml = dados.get("caminho_xml_nota_fiscal") or ""
    return {
        "ref": ref,
        "pack": str(pack),
        "conta": str(conta),
        "status": status,
        "numero": str(dados.get("numero") or ""),
        "serie": str(dados.get("serie") or ""),
        "chave": dados.get("chave_nfe") or "",
        "danfe_url": (_BASE + danfe) if danfe else "",
        "xml_url": (_BASE + xml) if xml else "",
        "mensagem": (dados.get("mensagem_sefaz") or dados.get("mensagem")
                     or dados.get("erros") or ""),
        "atualizado_em": time.time(),
    }


# --------------------------------------------------------------------------- #
# Persistencia (banco ou arquivo)
# --------------------------------------------------------------------------- #
if DATABASE_URL:
    import psycopg2

    def _conn():
        return psycopg2.connect(DATABASE_URL)

    def _init() -> None:
        with _conn() as c, c.cursor() as cur:
            cur.execute("CREATE TABLE IF NOT EXISTS nota_fiscal ("
                        "ref TEXT PRIMARY KEY, pack TEXT, conta TEXT, status TEXT, "
                        "numero TEXT, serie TEXT, chave TEXT, danfe_url TEXT, "
                        "xml_url TEXT, mensagem TEXT, criado_em DOUBLE PRECISION, "
                        "atualizado_em DOUBLE PRECISION)")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_nota_pack ON nota_fiscal(pack)")
            c.commit()

    _init()

    def _guardar(reg: dict) -> None:
        with _conn() as c, c.cursor() as cur:
            cur.execute(
                "INSERT INTO nota_fiscal (ref, pack, conta, status, numero, serie, "
                "chave, danfe_url, xml_url, mensagem, criado_em, atualizado_em) "
                "VALUES (%(ref)s,%(pack)s,%(conta)s,%(status)s,%(numero)s,%(serie)s,"
                "%(chave)s,%(danfe_url)s,%(xml_url)s,%(mensagem)s,%(criado_em)s,"
                "%(atualizado_em)s) ON CONFLICT (ref) DO UPDATE SET status=EXCLUDED.status,"
                "numero=EXCLUDED.numero, serie=EXCLUDED.serie, chave=EXCLUDED.chave,"
                "danfe_url=EXCLUDED.danfe_url, xml_url=EXCLUDED.xml_url,"
                "mensagem=EXCLUDED.mensagem, atualizado_em=EXCLUDED.atualizado_em",
                reg,
            )
            c.commit()

    _CAMPOS = ["ref", "pack", "conta", "status", "numero", "serie", "chave",
               "danfe_url", "xml_url", "mensagem"]

    def por_pack(pack: str) -> dict | None:
        with _conn() as c, c.cursor() as cur:
            cur.execute(f"SELECT {','.join(_CAMPOS)} FROM nota_fiscal WHERE pack=%s "
                        "ORDER BY criado_em DESC LIMIT 1", (str(pack),))
            r = cur.fetchone()
        return dict(zip(_CAMPOS, r)) if r else None

    def listar_balcao(limite: int = 50) -> list[dict]:
        with _conn() as c, c.cursor() as cur:
            cur.execute(f"SELECT {','.join(_CAMPOS)} FROM nota_fiscal "
                        "WHERE pack LIKE 'balcao-%%' ORDER BY criado_em DESC LIMIT %s",
                        (limite,))
            return [dict(zip(_CAMPOS, r)) for r in cur.fetchall()]

else:

    def _load() -> dict:
        if _ARQ.exists():
            return json.loads(_ARQ.read_text(encoding="utf-8"))
        return {}

    def _save(d: dict) -> None:
        _ARQ.write_text(json.dumps(d, indent=2), encoding="utf-8")

    def _guardar(reg: dict) -> None:
        d = _load()
        d[reg["ref"]] = reg
        _save(d)

    def por_pack(pack: str) -> dict | None:
        regs = [r for r in _load().values() if str(r.get("pack")) == str(pack)]
        regs.sort(key=lambda r: r.get("criado_em") or 0, reverse=True)
        return regs[0] if regs else None

    def listar_balcao(limite: int = 50) -> list[dict]:
        regs = [r for r in _load().values() if str(r.get("pack", "")).startswith("balcao-")]
        regs.sort(key=lambda r: r.get("criado_em") or 0, reverse=True)
        return regs[:limite]


# --------------------------------------------------------------------------- #
# API do modulo (usada pelo main.py)
# --------------------------------------------------------------------------- #
def emitir(pack: str, conta: str, payload: dict) -> dict:
    """Emite a NF-e do pedido `pack`. Retorna o registro guardado (com status)."""
    if not configurado():
        raise RuntimeError("Emissao de NF ainda nao configurada (sem token do Focus NFe).")
    ref = f"pack-{pack}-{int(time.time())}"
    resp = _emitir_focus(ref, payload)
    reg = _normaliza(ref, pack, conta, resp)
    reg["criado_em"] = time.time()
    _guardar(reg)
    return reg


def atualizar(ref: str) -> dict | None:
    """Reconsulta o status de uma NF no Focus e atualiza o registro guardado."""
    if not configurado():
        return None
    resp = _consultar_focus(ref)
    # preserva pack/conta ja guardados
    existente = None
    if DATABASE_URL:
        with _conn() as c, c.cursor() as cur:
            cur.execute("SELECT pack, conta, criado_em FROM nota_fiscal WHERE ref=%s", (ref,))
            existente = cur.fetchone()
        pack = existente[0] if existente else ""
        conta = existente[1] if existente else ""
        criado = existente[2] if existente else time.time()
    else:
        r = _load().get(ref) or {}
        pack, conta, criado = r.get("pack", ""), r.get("conta", ""), r.get("criado_em", time.time())
    reg = _normaliza(ref, pack, conta, resp)
    reg["criado_em"] = criado
    _guardar(reg)
    return reg
