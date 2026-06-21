"""App de teste: autentica no Bling e lista os pedidos reais numa telinha.

Rodar:
    uvicorn app.main:app --reload
Depois abra http://localhost:8000 no navegador.
"""
import secrets

import httpx
from pathlib import Path

from fastapi import FastAPI, Form, Request
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse, Response
from starlette.middleware.sessions import SessionMiddleware

from . import bling, categorias, config, mercadolivre

app = FastAPI(title="Hub de atendimento")

# rotas acessiveis sem login
_LIVRES = {"/entrar", "/sair", "/logo.png"}


@app.middleware("http")
async def _exige_login(request: Request, call_next):
    """Exige sessao logada. Desligado se APP_PASSWORD estiver vazio (uso local)."""
    if config.APP_PASSWORD and request.url.path not in _LIVRES:
        if not request.session.get("auth"):
            return RedirectResponse("/entrar")
    return await call_next(request)


# Adicionado DEPOIS do middleware acima -> fica mais externo -> request.session
# ja estara disponivel quando _exige_login rodar.
app.add_middleware(SessionMiddleware, secret_key=config.SESSION_SECRET, max_age=60 * 60 * 12)


def _pagina_login(erro: str = "") -> HTMLResponse:
    msg = f"<p style='color:#A32D2D;font-size:13px;margin:0 0 10px'>{erro}</p>" if erro else ""
    corpo = (
        "<div class='card' style='max-width:330px;margin:70px auto'>"
        "<div style='text-align:center;margin-bottom:18px'>"
        "<img src='/logo.png' style='width:60px;height:60px;border-radius:50%'/>"
        "<h3 style='margin:10px 0 0'>Hub de atendimento</h3></div>"
        f"{msg}"
        "<form method='post' action='/entrar'>"
        "<label style='font-size:13px;color:#5b6573'>Usuario</label>"
        "<input name='usuario' autofocus required "
        "style='width:100%;padding:10px;margin:4px 0 12px;border:1px solid #d7dade;border-radius:8px'/>"
        "<label style='font-size:13px;color:#5b6573'>Senha</label>"
        "<input name='senha' type='password' required "
        "style='width:100%;padding:10px;margin:4px 0 16px;border:1px solid #d7dade;border-radius:8px'/>"
        "<button class='btn' style='width:100%'>Entrar</button>"
        "</form></div>"
    )
    html = ("<!doctype html><html lang='pt-br'><meta charset='utf-8'>"
            "<meta name='viewport' content='width=device-width, initial-scale=1'>"
            f"<title>Entrar</title><style>{_CSS}</style>{corpo}</html>")
    return HTMLResponse(html)


@app.get("/entrar", response_class=HTMLResponse)
def entrar_form():
    return _pagina_login()


@app.post("/entrar")
def entrar(request: Request, usuario: str = Form(...), senha: str = Form(...)):
    ok = (secrets.compare_digest(usuario, config.APP_USER)
          and secrets.compare_digest(senha, config.APP_PASSWORD or ""))
    if ok:
        request.session["auth"] = True
        return RedirectResponse("/", status_code=303)
    return _pagina_login("Usuario ou senha incorretos.")


@app.get("/sair")
def sair(request: Request):
    request.session.clear()
    return RedirectResponse("/entrar", status_code=303)

# guarda o "state" do OAuth para validar o retorno (em memoria, suficiente p/ teste)
_pending_state: dict[str, bool] = {}


_CSS = """
*{box-sizing:border-box}
body{font-family:-apple-system,Segoe UI,Roboto,system-ui,sans-serif;margin:0;
     background:#f4f5f7;color:#1f2430}
a{color:inherit;text-decoration:none}
.nav{display:flex;align-items:center;justify-content:space-between;gap:16px;
     background:#fff;border-bottom:1px solid #e6e8eb;padding:10px 20px;position:sticky;top:0;z-index:5}
.brand{display:flex;align-items:center;gap:10px;font-weight:600;font-size:15px}
.brand img{width:30px;height:30px;border-radius:50%}
.nav .links{display:flex;gap:6px}
.nav .links a{padding:7px 13px;border-radius:8px;font-size:14px;color:#5b6573}
.nav .links a:hover{background:#f0f1f4}
.nav .links a.on{background:#EEEDFE;color:#3C3489}
.wrap{max-width:880px;margin:28px auto;padding:0 18px}
.btn{display:inline-block;background:#2D3277;color:#fff;padding:11px 20px;border-radius:9px;
     font-size:14px;border:none;cursor:pointer}
.btn.ml{background:#FFE600;color:#2D3277}
.btn.ghost{background:#fff;border:1px solid #d7dade;color:#1f2430}
.card{background:#fff;border:1px solid #e6e8eb;border-radius:12px;padding:18px 20px;margin:14px 0}
.pill{font-size:12px;padding:2px 10px;border-radius:999px;background:#EEF2F6;color:#41506b}
.muted{color:#8a93a0;font-size:13px}
table{border-collapse:collapse;width:100%;font-size:14px}
th,td{text-align:left;padding:9px 10px;border-bottom:1px solid #eef0f2}
th{color:#7a828e;font-weight:500}
h1{font-size:22px}h3{font-size:16px;font-weight:600}
/* ---- caixa de entrada ---- */
.inbox{display:grid;grid-template-columns:188px var(--mid,320px) 6px 1fr;height:calc(100vh - 53px)}
.splitter{background:#e6e8eb;cursor:col-resize}
.splitter:hover,.splitter.act{background:#FFE600}
.rail{background:#fff;border-right:1px solid #e6e8eb;padding:12px 10px;overflow-y:auto}
.chan{display:flex;align-items:center;gap:9px;padding:9px 11px;border-radius:9px;cursor:pointer;
      font-size:14px;color:#41506b;margin-bottom:3px}
.chan:hover{background:#f3f4f6}
.chan.on{background:#EEEDFE;color:#3C3489;font-weight:600}
.chan.off{opacity:.45;cursor:default}
.chan .dot{width:9px;height:9px;border-radius:50%}
.clist{background:#fafbfc;border-right:1px solid #e6e8eb;overflow-y:auto}
.ci{display:block;padding:12px 14px;border-bottom:1px solid #eef0f2;cursor:pointer}
.ci:hover{background:#f1f3f5}
.ci.on{background:#fff;box-shadow:inset 3px 0 0 #FFE600}
.ci .top{display:flex;justify-content:space-between;gap:8px}
.ci .nm{font-weight:600;font-size:14px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.ci .pv{font-size:12.5px;color:#7a828e;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;margin-top:3px}
.badge{font-size:10.5px;padding:1px 8px;border-radius:999px}
.detail{display:flex;flex-direction:column;min-height:0;background:#fff}
.dhead{display:flex;align-items:center;gap:11px;padding:13px 18px;border-bottom:1px solid #e6e8eb}
.av{width:38px;height:38px;border-radius:50%;display:flex;align-items:center;justify-content:center;
    font-weight:600;font-size:13px}
.ordbar{padding:10px 18px;background:#fafbfc;border-bottom:1px solid #eef0f2;font-size:12.5px;
        color:#5b6573;display:flex;gap:16px;flex-wrap:wrap}
.thread{flex:1;overflow-y:auto;padding:16px 18px;display:flex;flex-direction:column;gap:8px;background:#f7f8fa}
.bub{max-width:72%;padding:8px 12px;border-radius:12px;font-size:13.5px;line-height:1.5}
.bub.me{align-self:flex-end;background:#DCF7E3}
.bub.them{align-self:flex-start;background:#fff;border:1px solid #eceef0}
.bub .t{font-size:10.5px;color:#9aa2ad;margin-top:3px;text-align:right}
.reply{display:flex;gap:9px;padding:12px 18px;border-top:1px solid #e6e8eb}
.reply input{flex:1;padding:11px 13px;border:1px solid #d7dade;border-radius:10px;font-size:14px}
.empty{flex:1;display:flex;flex-direction:column;align-items:center;justify-content:center;color:#9aa2ad;gap:8px}
"""


def _pagina(corpo: str, full: bool = False, ativo: str = "") -> HTMLResponse:
    def lk(href, label, key):
        return f"<a href='{href}' class='{'on' if ativo == key else ''}'>{label}</a>"
    nav = (
        "<div class='nav'>"
        "<a class='brand' href='/'><img src='/logo.png' alt='logo'/>"
        "<span>Hub de atendimento</span></a>"
        "<div class='links'>"
        + lk("/inbox", "Caixa de entrada", "inbox")
        + lk("/pedidos", "Pedidos (Bling)", "pedidos")
        + ("<a href='/sair'>Sair</a>" if config.APP_PASSWORD else "")
        + "</div></div>"
    )
    miolo = corpo if full else f"<div class='wrap'>{corpo}</div>"
    html = (
        "<!doctype html><html lang='pt-br'><meta charset='utf-8'>"
        "<meta name='viewport' content='width=device-width, initial-scale=1'>"
        f"<title>Hub de atendimento</title><style>{_CSS}</style>{nav}{miolo}</html>"
    )
    return HTMLResponse(html)


@app.get("/logo.png")
def logo():
    return FileResponse(config.BASE_DIR / "helloow-logo.png")


@app.get("/", response_class=HTMLResponse)
def home():
    if not config.is_configured():
        return _pagina(
            "<h1>Hub de atendimento</h1>"
            "<p style='color:#A32D2D'>Faltam credenciais do Bling no <code>.env</code>.</p>"
        )
    bling_ok = bling.carregar_token() is not None
    ml_contas = mercadolivre.contas() if config.is_ml_configured() else []
    ml_ok = bool(ml_contas)

    if bling_ok and ml_ok:
        destaque = (
            "<div class='card' style='border-color:#FFE600'>"
            "<h3>Caixa de entrada unificada</h3>"
            "<p class='muted'>Pedidos do Bling e mensagens do Mercado Livre num lugar so.</p>"
            "<p><a class='btn ml' href='/inbox'>Abrir caixa de entrada &rarr;</a></p></div>"
        )
    else:
        destaque = ""

    if bling_ok:
        b = "<p>&#10003; Bling conectado.</p>"
    else:
        b = "<p><a class='btn' href='/login'>Conectar ao Bling</a></p>"

    if not config.is_ml_configured():
        m = "<p class='muted'>Mercado Livre: faltam credenciais no .env.</p>"
    elif ml_contas:
        nomes = ", ".join(mercadolivre.nome_exibicao(c) for c in ml_contas)
        m = (f"<p>&#10003; Mercado Livre: <b>{len(ml_contas)}</b> conta(s) &mdash; {nomes}</p>"
             "<p><a class='btn ghost' href='/ml/login'>+ Conectar outra conta</a> "
             "<a class='btn ghost' href='/lojas'>Renomear lojas</a></p>")
    else:
        m = "<p><a class='btn ml' href='/ml/login'>Conectar ao Mercado Livre</a></p>"

    corpo = (
        "<h1>Hub de atendimento &middot; Grafica Betinho</h1>"
        + destaque
        + "<div class='card'><h3>Conexoes</h3>" + b + m + "</div>"
    )
    return _pagina(corpo)


@app.get("/login")
def login():
    state = secrets.token_urlsafe(16)
    _pending_state[state] = True
    return RedirectResponse(bling.montar_url_autorizacao(state))


@app.get("/callback")
def callback(request: Request):
    params = request.query_params
    code = params.get("code")
    state = params.get("state", "")
    if not code:
        return _pagina(f"<h1>Erro</h1><p>Bling nao retornou um code. Parametros: {dict(params)}</p>")
    if state not in _pending_state:
        return _pagina("<h1>Erro</h1><p>State invalido (possivel CSRF). Tente de novo em /login.</p>")
    _pending_state.pop(state, None)
    try:
        bling.trocar_codigo_por_token(code)
    except httpx.HTTPStatusError as e:
        return _pagina(f"<h1>Falha ao obter token</h1><pre>{e.response.text}</pre>")
    return RedirectResponse("/pedidos")


def _data_br(iso: str) -> str:
    """Converte '2026-06-10' (ou '2026-06-10 14:30:00') para '10/06/2026'."""
    if not iso:
        return "-"
    d = str(iso)[:10]
    partes = d.split("-")
    return f"{partes[2]}/{partes[1]}/{partes[0]}" if len(partes) == 3 else d


@app.get("/pedidos", response_class=HTMLResponse)
def pedidos(pagina: int = 1):
    pagina = max(1, pagina)
    try:
        lista = bling.listar_pedidos(pagina=pagina, limite=100)
    except RuntimeError:
        return RedirectResponse("/login")
    except httpx.HTTPStatusError as e:
        return _pagina(f"<h1>Erro na API</h1><pre>{e.response.text}</pre>")

    # ordena por data do pedido, mais recentes primeiro
    lista.sort(key=lambda p: str(p.get("data") or ""), reverse=True)

    linhas = ""
    for p in lista:
        contato = (p.get("contato") or {}).get("nome", "-")
        loja = (p.get("loja") or {}).get("id", "-")
        total = p.get("total", 0)
        situacao = (p.get("situacao") or {}).get("valor", "-")
        pid = p.get("id", "")
        linhas += (
            f"<tr><td>{_data_br(p.get('data'))}</td>"
            f"<td>{p.get('numero','-')}</td><td>{contato}</td>"
            f"<td><span class='pill'>loja {loja}</span></td>"
            f"<td>R$ {total}</td><td>{situacao}</td>"
            f"<td><a href='/pedido/{pid}'>abrir &rarr;</a></td></tr>"
        )
    if not linhas:
        linhas = "<tr><td colspan='7' class='muted'>Nenhum pedido nesta pagina.</td></tr>"

    # navegacao: avanca se a pagina veio cheia (100)
    nav = "<div style='margin-top:16px;display:flex;gap:10px;align-items:center'>"
    if pagina > 1:
        nav += f"<a class='btn ghost' href='/pedidos?pagina={pagina-1}'>&larr; Anteriores</a>"
    nav += f"<span class='muted'>Pagina {pagina}</span>"
    if len(lista) >= 100:
        nav += f"<a class='btn ghost' href='/pedidos?pagina={pagina+1}'>Proximos &rarr;</a>"
    nav += "</div>"

    corpo = (
        "<h1>Pedidos (Bling)</h1>"
        "<p class='muted'>Ordenados pela data do pedido (mais recentes primeiro) &middot; "
        "100 por pagina</p>"
        "<table><tr><th>Data</th><th>Pedido</th><th>Cliente</th><th>Canal/Loja</th>"
        f"<th>Total</th><th>Situacao</th><th></th></tr>{linhas}</table>"
        f"{nav}"
        "<p style='margin-top:16px'><a href='/'>&larr; inicio</a></p>"
    )
    return _pagina(corpo, ativo="pedidos")


@app.get("/pedido/{pedido_id}", response_class=HTMLResponse)
def pedido_detalhe(pedido_id: str):
    try:
        ped = bling.obter_pedido(pedido_id)
    except RuntimeError:
        return RedirectResponse("/login")
    except httpx.HTTPStatusError as e:
        return _pagina(f"<h1>Erro na API</h1><pre>{e.response.text}</pre>")

    contato_resumo = ped.get("contato") or {}
    contato_id = contato_resumo.get("id")
    nome = contato_resumo.get("nome", "-")
    loja = (ped.get("loja") or {}).get("id", "-")
    situacao = (ped.get("situacao") or {}).get("valor", "-")
    total = ped.get("total", 0)

    # Tenta buscar telefone/email completos (precisa do escopo "Contatos")
    telefone = email = doc = None
    aviso_escopo = ""
    if contato_id:
        try:
            c = bling.obter_contato(contato_id)
            telefone = c.get("celular") or c.get("telefone")
            email = c.get("email")
            doc = c.get("numeroDocumento")
            if not nome or nome == "-":
                nome = c.get("nome", nome)
        except httpx.HTTPStatusError as e:
            if e.response.status_code in (401, 403):
                aviso_escopo = (
                    "<p style='color:#A32D2D'>Para puxar telefone/e-mail do cliente, "
                    "adicione o escopo <b>Contatos</b> no app do Bling e refaca o login.</p>"
                )
            else:
                raise

    # Itens do pedido
    itens_html = ""
    for it in ped.get("itens", []):
        itens_html += (
            f"<tr><td>{it.get('quantidade','-')}x</td>"
            f"<td>{it.get('descricao','-')}</td>"
            f"<td>R$ {it.get('valor','-')}</td></tr>"
        )
    if not itens_html:
        itens_html = "<tr><td colspan='3' class='muted'>Sem itens.</td></tr>"

    # Acoes de contato
    wpp = bling.normalizar_whatsapp(telefone)
    acoes = ""
    if wpp:
        msg = f"Ola {nome.split(' ')[0]}, aqui e da Grafica Betinho sobre o seu pedido {ped.get('numero','')}."
        from urllib.parse import quote
        link = f"https://wa.me/{wpp}?text={quote(msg)}"
        acoes += (
            f"<a class='btn' style='background:#1D9E75' href='{link}' target='_blank'>"
            "Falar no WhatsApp</a> "
        )
    if email:
        acoes += f"<a class='btn' style='background:#444' href='mailto:{email}'>Enviar e-mail</a>"
    if not acoes:
        acoes = "<span class='muted'>Sem telefone/e-mail disponivel para contato.</span>"

    corpo = (
        f"<p><a href='/pedidos'>&larr; voltar aos pedidos</a></p>"
        f"<h1>Pedido {ped.get('numero','-')}</h1>"
        f"<p><span class='pill'>loja {loja}</span> &middot; {situacao} &middot; "
        f"<b>R$ {total}</b></p>"
        f"{aviso_escopo}"
        "<h3 style='margin-top:24px'>Cliente</h3>"
        "<table>"
        f"<tr><th>Nome</th><td>{nome}</td></tr>"
        f"<tr><th>WhatsApp / Telefone</th><td>{telefone or '-'}</td></tr>"
        f"<tr><th>E-mail</th><td>{email or '-'}</td></tr>"
        f"<tr><th>Documento</th><td>{doc or '-'}</td></tr>"
        "</table>"
        f"<p style='margin-top:16px'>{acoes}</p>"
        "<h3 style='margin-top:24px'>Itens</h3>"
        f"<table><tr><th>Qtd</th><th>Produto</th><th>Valor</th></tr>{itens_html}</table>"
    )
    return _pagina(corpo)


# =========================================================================== #
# Mercado Livre - mensagens dos compradores
# =========================================================================== #
@app.get("/ml/login")
def ml_login():
    state = secrets.token_urlsafe(16)
    _pending_state[state] = True
    return RedirectResponse(mercadolivre.montar_url_autorizacao(state))


@app.get("/ml/callback")
def ml_callback(request: Request):
    params = request.query_params
    code = params.get("code")
    state = params.get("state", "")
    if not code:
        return _pagina(f"<h1>Erro</h1><p>Mercado Livre nao retornou code. {dict(params)}</p>")
    if state not in _pending_state:
        return _pagina("<h1>Erro</h1><p>State invalido. Tente de novo em /ml/login.</p>")
    _pending_state.pop(state, None)
    try:
        mercadolivre.trocar_codigo_por_token(code)
    except httpx.HTTPStatusError as e:
        return _pagina(f"<h1>Falha ao obter token (ML)</h1><pre>{e.response.text}</pre>")
    return RedirectResponse("/inbox")


@app.get("/ml/mensagens", response_class=HTMLResponse)
def ml_mensagens():
    try:
        pedidos = mercadolivre.listar_pedidos(limite=15)
    except RuntimeError:
        return RedirectResponse("/ml/login")
    except httpx.HTTPStatusError as e:
        return _pagina(f"<h1>Erro na API (ML)</h1><pre>{e.response.text}</pre>")

    linhas = ""
    for o in pedidos:
        comprador = (o.get("buyer") or {}).get("nickname", "-")
        comprador_id = (o.get("buyer") or {}).get("id", "")
        pack = o.get("pack_id") or o.get("id")
        titulo = "-"
        itens = o.get("order_items") or []
        if itens:
            titulo = (itens[0].get("item") or {}).get("title", "-")
        status = o.get("status", "-")
        linhas += (
            f"<tr><td>{o.get('id','-')}</td><td>{comprador}</td>"
            f"<td>{titulo[:50]}</td><td>{status}</td>"
            f"<td><a href='/ml/conversa/{pack}?buyer={comprador_id}'>ver mensagens &rarr;</a></td></tr>"
        )
    if not linhas:
        linhas = "<tr><td colspan='5' class='muted'>Nenhum pedido recente no Mercado Livre.</td></tr>"

    corpo = (
        "<p><a href='/'>&larr; inicio</a></p>"
        "<h1>Mercado Livre &middot; pedidos recentes</h1>"
        "<p class='muted'>Clique em \"ver mensagens\" para abrir a conversa com o comprador.</p>"
        "<table><tr><th>Pedido</th><th>Comprador</th><th>Produto</th>"
        f"<th>Status</th><th></th></tr>{linhas}</table>"
    )
    return _pagina(corpo)


def _render_conversa(pack_id: str, buyer: str, aviso: str = "") -> HTMLResponse:
    try:
        mensagens = mercadolivre.listar_mensagens(pack_id)
    except RuntimeError:
        return RedirectResponse("/ml/login")
    except httpx.HTTPStatusError as e:
        return _pagina(f"<h1>Erro na API (ML)</h1><pre>{e.response.text}</pre>")

    sid = mercadolivre.seller_id()
    baloes = ""
    for m in mensagens:
        de = str((m.get("from") or {}).get("user_id", ""))
        sou_eu = de == str(sid)
        texto = (m.get("text") or "").replace("<", "&lt;")
        cor = "#DCF8C6" if sou_eu else "#F1F0F0"
        lado = "right" if sou_eu else "left"
        quem = "Voce (loja)" if sou_eu else "Comprador"
        baloes += (
            f"<div style='text-align:{lado}; margin:6px 0;'>"
            f"<div style='display:inline-block; background:{cor}; padding:8px 12px; "
            f"border-radius:10px; max-width:70%; text-align:left;'>"
            f"<div style='font-size:11px; color:#777'>{quem}</div>{texto}</div></div>"
        )
    if not baloes:
        baloes = "<p class='muted'>Sem mensagens nesta conversa ainda.</p>"

    corpo = (
        "<p><a href='/ml/mensagens'>&larr; voltar</a></p>"
        f"<h1>Conversa &middot; pack {pack_id}</h1>"
        f"{aviso}"
        f"<div style='border:1px solid #eee; border-radius:8px; padding:12px; "
        f"background:#fafafa;'>{baloes}</div>"
        f"<form method='post' action='/ml/conversa/{pack_id}' style='margin-top:14px; "
        "display:flex; gap:8px;'>"
        f"<input type='hidden' name='buyer' value='{buyer}'/>"
        "<input name='texto' placeholder='Responder o comprador...' "
        "style='flex:1; padding:10px; border:1px solid #ccc; border-radius:8px;' required/>"
        "<button class='btn' style='background:#FFE600;color:#2D3277; border:none;' "
        "type='submit'>Enviar</button></form>"
    )
    return _pagina(corpo)


@app.get("/ml/conversa/{pack_id}", response_class=HTMLResponse)
def ml_conversa(pack_id: str, buyer: str = ""):
    return _render_conversa(pack_id, buyer)


@app.post("/ml/conversa/{pack_id}", response_class=HTMLResponse)
def ml_responder(pack_id: str, buyer: str = Form(""), texto: str = Form(...)):
    aviso = ""
    try:
        mercadolivre.enviar_mensagem(pack_id, buyer, texto)
        aviso = "<p style='color:#0F6E56'>Mensagem enviada ao comprador.</p>"
    except httpx.HTTPStatusError as e:
        aviso = f"<p style='color:#A32D2D'>Falha ao enviar: <pre>{e.response.text}</pre></p>"
    except RuntimeError:
        return RedirectResponse("/ml/login")
    return _render_conversa(pack_id, buyer, aviso)


# =========================================================================== #
# Caixa de entrada unificada (visual de produto)
# =========================================================================== #
def _badge_status(status: str) -> str:
    mapa = {
        "paid": ("#E1F5EE", "#0F6E56", "Pago"),
        "confirmed": ("#E6F1FB", "#0C447C", "Confirmado"),
        "cancelled": ("#FCEBEB", "#A32D2D", "Cancelado"),
        "invalid": ("#FCEBEB", "#A32D2D", "Invalido"),
    }
    bg, fg, txt = mapa.get(status, ("#EEF2F6", "#41506b", status or "-"))
    return f"<span class='badge' style='background:{bg};color:{fg}'>{txt}</span>"


def _eh_imagem(nome: str) -> bool:
    nome = (nome or "").lower()
    return nome.endswith((".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp"))


def _anexos_html(m: dict, conta: str) -> str:
    """Renderiza anexos (arte do cliente) de uma mensagem do Mercado Livre."""
    out = ""
    anexos = m.get("message_attachments") or m.get("attachments") or []
    for a in anexos:
        if isinstance(a, str):
            fn, orig = a, a
        else:
            fn = a.get("filename") or a.get("id")
            orig = a.get("original_filename") or fn or "arquivo"
        if not fn:
            continue
        url = f"/ml/anexo/{conta}/{fn}"
        if _eh_imagem(orig):
            out += (f"<a href='{url}' target='_blank'>"
                    f"<img src='{url}' loading='lazy' "
                    "style='max-width:230px;border-radius:8px;margin-top:6px;display:block'/></a>")
        else:
            safe = (orig or "arquivo").replace("<", "&lt;")
            out += (f"<a href='{url}' target='_blank' "
                    "style='display:inline-flex;align-items:center;gap:5px;margin-top:6px'>"
                    f"<i class='ti ti-paperclip'></i> {safe}</a>")
    return out


def _rail(cats: list, cat_atual: str) -> str:
    def item(nome, cor, on=False, off=False):
        cls = "chan" + (" on" if on else "") + (" off" if off else "")
        tag = "" if not off else "<span class='muted' style='font-size:11px'>em breve</span>"
        return (f"<div class='{cls}'><span class='dot' style='background:{cor}'></span>"
                f"<span style='flex:1'>{nome}</span>{tag}</div>")

    canais = (
        "<div class='muted' style='padding:4px 11px 8px;font-size:11px'>CANAIS</div>"
        + item("Todos", "#8a93a0", on=True)
        + item("Mercado Livre", "#FFE600", on=True)
        + item("Shopee", "#EE4D2D", off=True)
        + item("Amazon", "#FF9900", off=True)
        + item("WhatsApp", "#25D366", off=True)
    )

    def catlink(label, valor, ativo, icone="ti-tag"):
        cls = "chan" + (" on" if ativo else "")
        return (f"<a class='{cls}' href='/inbox?cat={valor}'>"
                f"<i class='ti {icone}' style='font-size:15px'></i>"
                f"<span style='flex:1'>{label}</span></a>")

    cats_html = "<div class='muted' style='padding:14px 11px 6px;font-size:11px'>CATEGORIAS</div>"
    cats_html += catlink("Todas", "", cat_atual == "", "ti-stack")
    for c in cats:
        cats_html += catlink(c["nome"], str(c["id"]), cat_atual == str(c["id"]))
    cats_html += catlink("Sem categoria", "none", cat_atual == "none", "ti-tag-off")
    cats_html += ("<a class='chan' href='/categorias' style='color:#534AB7'>"
                  "<i class='ti ti-settings' style='font-size:15px'></i>"
                  "<span style='flex:1'>Gerenciar</span></a>")

    return "<div class='rail'>" + canais + cats_html + "</div>"


_SPLIT_JS = """
<script>
(function(){
  var inbox=document.querySelector('.inbox'),split=document.getElementById('split');
  if(!inbox||!split)return;
  var saved=localStorage.getItem('midw');
  if(saved)inbox.style.setProperty('--mid',saved+'px');
  var drag=false,lastw=null;
  split.addEventListener('mousedown',function(e){drag=true;split.classList.add('act');
    document.body.style.userSelect='none';e.preventDefault();});
  window.addEventListener('mousemove',function(e){
    if(!drag)return;
    var rect=inbox.getBoundingClientRect();
    var w=e.clientX-rect.left-188;
    if(w<220)w=220;if(w>760)w=760;
    lastw=Math.round(w);inbox.style.setProperty('--mid',lastw+'px');
  });
  window.addEventListener('mouseup',function(){
    if(!drag)return;drag=false;split.classList.remove('act');
    document.body.style.userSelect='';
    if(lastw)localStorage.setItem('midw',lastw);
  });
  // rola a conversa para a ultima mensagem
  var th=document.querySelector('.thread');if(th)th.scrollTop=th.scrollHeight;
  // auto-atualiza a cada 25s, mas NAO enquanto o usuario digita uma resposta
  setInterval(function(){
    var inp=document.querySelector('.reply input[name=texto]');
    if(inp&&(inp.value.trim()!==''||document.activeElement===inp))return;
    if(drag)return;
    location.reload();
  },25000);
})();
</script>
"""


@app.get("/inbox", response_class=HTMLResponse)
def inbox(pack: str = "", buyer: str = "", conta: str = "", cat: str = ""):
    contas = mercadolivre.contas()
    if not contas:
        return RedirectResponse("/ml/login")

    cats = categorias.listar_categorias()
    nomes_cat = {c["id"]: c["nome"] for c in cats}
    marcas = categorias.marcas()  # pack -> categoria_id

    # ---- lista de conversas (somando todas as contas) ----
    itens = ""
    selecionado = None
    sel_conta = None
    for acc in contas:
        uid = str(acc["user_id"])
        apelido = mercadolivre.nome_exibicao(acc)
        try:
            pedidos = mercadolivre.listar_pedidos(limite=15, user_id=uid)
        except (RuntimeError, httpx.HTTPStatusError):
            pedidos = []
        for o in pedidos:
            comprador = (o.get("buyer") or {}).get("nickname", "-")
            comprador_id = str((o.get("buyer") or {}).get("id", ""))
            pk = str(o.get("pack_id") or o.get("id"))
            produtos = o.get("order_items") or []
            titulo = (produtos[0].get("item") or {}).get("title", "-") if produtos else "-"
            cat_id = marcas.get(pk)
            cat_nome = nomes_cat.get(cat_id) if cat_id else None
            on = pk == pack and uid == conta
            if on:
                selecionado, sel_conta = o, acc
            # filtro por categoria
            if cat == "none" and cat_id:
                continue
            if cat and cat != "none" and str(cat_id) != cat:
                continue
            etiqueta = (f"<div style='margin-top:5px'><span class='badge' "
                        f"style='background:#EEEDFE;color:#3C3489'>{cat_nome}</span></div>"
                        if cat_nome else "")
            itens += (
                f"<a class='ci {'on' if on else ''}' "
                f"href='/inbox?pack={pk}&buyer={comprador_id}&conta={uid}&cat={cat}'>"
                "<div class='top'>"
                f"<span class='nm'>{comprador}</span>"
                f"<span class='badge' style='background:#FFF7CC;color:#7a6a00'>{apelido}</span>"
                "</div>"
                f"<div class='pv'>{titulo}</div>{etiqueta}</a>"
            )
    if not itens:
        itens = "<div style='padding:16px' class='muted'>Nenhuma conversa nesta categoria.</div>"

    # ---- painel de detalhe ----
    if selecionado is None:
        detalhe = ("<div class='empty'><i class='ti ti-messages' "
                   "style='font-size:34px'></i><div>Selecione uma conversa</div></div>")
    else:
        comprador = (selecionado.get("buyer") or {}).get("nickname", "-")
        status = selecionado.get("status", "-")
        total = selecionado.get("total_amount", "-")
        produtos = selecionado.get("order_items") or []
        titulo = (produtos[0].get("item") or {}).get("title", "-") if produtos else "-"
        apelido = mercadolivre.nome_exibicao(sel_conta)
        try:
            mensagens = mercadolivre.listar_mensagens(pack, user_id=conta)
        except httpx.HTTPStatusError:
            mensagens = []
        sid = str(mercadolivre.seller_id(conta))
        baloes = ""
        for m in mensagens:
            eu = str((m.get("from") or {}).get("user_id", "")) == sid
            txt = (m.get("text") or "").replace("<", "&lt;")
            baloes += (f"<div class='bub {'me' if eu else 'them'}'>"
                       f"{txt}{_anexos_html(m, conta)}</div>")
        if not baloes:
            baloes = "<p class='muted'>Sem mensagens nesta conversa ainda.</p>"

        # seletor de categoria desta conversa
        cat_desta = marcas.get(pack)
        opcoes = "<option value=''>Sem categoria</option>"
        for c in cats:
            sel = " selected" if c["id"] == cat_desta else ""
            opcoes += f"<option value='{c['id']}'{sel}>{c['nome']}</option>"
        seletor = (
            "<form method='post' action='/categoria/marcar' style='display:inline-flex;align-items:center;gap:5px'>"
            f"<input type='hidden' name='pack' value='{pack}'/>"
            f"<input type='hidden' name='conta' value='{conta}'/>"
            f"<input type='hidden' name='buyer' value='{buyer}'/>"
            f"<input type='hidden' name='cat' value='{cat}'/>"
            "<i class='ti ti-tag'></i>"
            "<select name='categoria' onchange='this.form.submit()' "
            "style='font-size:12px;padding:3px 6px;border-radius:6px;border:1px solid #d7dade'>"
            f"{opcoes}</select></form>"
        )

        detalhe = (
            "<div class='dhead'>"
            f"<div class='av' style='background:#FFF7CC;color:#7a6a00'>{comprador[:2].upper()}</div>"
            f"<div style='flex:1'><div style='font-weight:600'>{comprador}</div>"
            f"<div class='muted' style='font-size:12px'>Mercado Livre &middot; {apelido}</div></div>"
            f"{_badge_status(status)}</div>"
            f"<div class='ordbar'><span><i class='ti ti-package'></i> {titulo}</span>"
            f"<span><i class='ti ti-cash'></i> R$ {total}</span>"
            f"{seletor}</div>"
            f"<div class='thread'>{baloes}</div>"
            f"<form class='reply' method='post' action='/inbox/responder'>"
            f"<input type='hidden' name='pack' value='{pack}'/>"
            f"<input type='hidden' name='buyer' value='{buyer}'/>"
            f"<input type='hidden' name='conta' value='{conta}'/>"
            "<input name='texto' placeholder='Responder o comprador...' required/>"
            "<button class='btn ml' type='submit'>Enviar</button></form>"
        )

    corpo = (
        "<link rel='stylesheet' href='https://cdn.jsdelivr.net/npm/"
        "@tabler/icons-webfont@3.11.0/dist/tabler-icons.min.css'>"
        "<div class='inbox'>"
        + _rail(cats, cat)
        + f"<div class='clist'>{itens}</div>"
        + "<div class='splitter' id='split'></div>"
        + f"<div class='detail'>{detalhe}</div>"
        + "</div>"
        + _SPLIT_JS
    )
    return _pagina(corpo, full=True, ativo="inbox")


@app.post("/inbox/responder")
def inbox_responder(pack: str = Form(...), buyer: str = Form(""),
                    conta: str = Form(""), texto: str = Form(...)):
    try:
        mercadolivre.enviar_mensagem(pack, buyer, texto, user_id=conta or None)
    except (RuntimeError, httpx.HTTPStatusError):
        pass
    return RedirectResponse(f"/inbox?pack={pack}&buyer={buyer}&conta={conta}", status_code=303)


@app.get("/ml/anexo/{conta}/{filename:path}")
def ml_anexo(conta: str, filename: str):
    """Baixa e serve um anexo (arte) de uma mensagem do Mercado Livre."""
    try:
        conteudo, ctype = mercadolivre.baixar_anexo(filename, user_id=conta)
    except Exception:
        return Response(status_code=404)
    return Response(content=conteudo, media_type=ctype)


# =========================================================================== #
# Categorias (etiquetas das conversas)
# =========================================================================== #
@app.post("/categoria/marcar")
def categoria_marcar(pack: str = Form(...), conta: str = Form(""), buyer: str = Form(""),
                     cat: str = Form(""), categoria: str = Form("")):
    categorias.marcar(pack, int(categoria) if categoria else None)
    return RedirectResponse(
        f"/inbox?pack={pack}&buyer={buyer}&conta={conta}&cat={cat}", status_code=303)


@app.get("/categorias", response_class=HTMLResponse)
def categorias_page():
    linhas = ""
    for c in categorias.listar_categorias():
        nome = c["nome"].replace('"', "&quot;")
        linhas += (
            "<div style='display:flex;gap:8px;align-items:center;margin:8px 0'>"
            "<form method='post' action='/categorias/renomear' style='display:flex;gap:6px;flex:1'>"
            f"<input type='hidden' name='id' value='{c['id']}'/>"
            f"<input name='nome' value=\"{nome}\" "
            "style='flex:1;padding:9px;border:1px solid #d7dade;border-radius:8px'/>"
            "<button class='btn ghost'>Salvar</button></form>"
            "<form method='post' action='/categorias/excluir' "
            "onsubmit=\"return confirm('Excluir esta categoria?')\">"
            f"<input type='hidden' name='id' value='{c['id']}'/>"
            "<button class='btn' style='background:#FCEBEB;color:#A32D2D'>Excluir</button></form>"
            "</div>"
        )
    if not linhas:
        linhas = "<p class='muted'>Nenhuma categoria ainda. Crie a primeira acima.</p>"
    corpo = (
        "<h1>Categorias</h1>"
        "<div class='card'>"
        "<form method='post' action='/categorias/criar' style='display:flex;gap:8px'>"
        "<input name='nome' placeholder='Nova categoria (ex: Adesivos)' required "
        "style='flex:1;padding:10px;border:1px solid #d7dade;border-radius:8px'/>"
        "<button class='btn'>Adicionar</button></form>"
        f"<div style='margin-top:16px'>{linhas}</div></div>"
        "<p><a href='/inbox'>&larr; voltar para a caixa de entrada</a></p>"
    )
    return _pagina(corpo, ativo="inbox")


@app.post("/categorias/criar")
def categorias_criar(nome: str = Form(...)):
    if nome.strip():
        categorias.criar_categoria(nome.strip())
    return RedirectResponse("/categorias", status_code=303)


@app.post("/categorias/renomear")
def categorias_renomear(id: int = Form(...), nome: str = Form(...)):
    if nome.strip():
        categorias.renomear_categoria(id, nome.strip())
    return RedirectResponse("/categorias", status_code=303)


@app.post("/categorias/excluir")
def categorias_excluir(id: int = Form(...)):
    categorias.excluir_categoria(id)
    return RedirectResponse("/categorias", status_code=303)


# =========================================================================== #
# Renomear lojas (apelido amigavel por conta do Mercado Livre)
# =========================================================================== #
@app.get("/lojas", response_class=HTMLResponse)
def lojas_page():
    linhas = ""
    for acc in mercadolivre.contas():
        uid = str(acc["user_id"])
        nick = acc.get("nickname") or uid
        atual = (mercadolivre.apelido_loja(uid) or "").replace('"', "&quot;")
        linhas += (
            "<div style='margin:12px 0'>"
            f"<div class='muted' style='font-size:12px'>Conta ML: {nick} &middot; id {uid}</div>"
            "<form method='post' action='/lojas/renomear' style='display:flex;gap:6px;margin-top:4px'>"
            f"<input type='hidden' name='uid' value='{uid}'/>"
            f"<input name='apelido' value=\"{atual}\" "
            "placeholder='Nome amigavel (ex: Loja Adesivos)' "
            "style='flex:1;padding:9px;border:1px solid #d7dade;border-radius:8px'/>"
            "<button class='btn ghost'>Salvar</button></form></div>"
        )
    if not linhas:
        linhas = "<p class='muted'>Nenhuma conta conectada.</p>"
    corpo = (
        "<h1>Renomear lojas</h1>"
        "<p class='muted'>Dê um nome amigável para cada conta do Mercado Livre. "
        "Vale só aqui no hub &mdash; não muda nada no Mercado Livre.</p>"
        f"<div class='card'>{linhas}</div>"
        "<p><a href='/inbox'>&larr; voltar para a caixa de entrada</a></p>"
    )
    return _pagina(corpo, ativo="inbox")


@app.post("/lojas/renomear")
def lojas_renomear(uid: str = Form(...), apelido: str = Form("")):
    mercadolivre.definir_apelido(uid, apelido.strip())
    return RedirectResponse("/lojas", status_code=303)
