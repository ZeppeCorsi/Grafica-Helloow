"""App de teste: autentica no Bling e lista os pedidos reais numa telinha.

Rodar:
    uvicorn app.main:app --reload
Depois abra http://localhost:8000 no navegador.
"""
import calendar
import concurrent.futures
import csv
import io
import json
import secrets
from datetime import date, datetime, timedelta

import httpx
from pathlib import Path
from urllib.parse import quote

from fastapi import FastAPI, File, Form, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse, Response
from starlette.middleware.sessions import SessionMiddleware

from . import (backup, balcao, bling, categorias, config, financeiro, fluxos,
               ia_consumo, mercadolivre, nfe, produtos, store, usuarios)

app = FastAPI(title="Hub de atendimento")

# rotas acessiveis sem login
_LIVRES = {"/", "/entrar", "/sair", "/logo.png", "/favicon.svg"}

# Icone do Zappe Hub (inline, para cabecalho e login)
_ICONE = (
    "<svg viewBox='0 0 44 50' width='28' height='32' style='flex:none' aria-hidden='true'>"
    "<rect x='3' y='3' width='38' height='34' rx='9' fill='#5546E8'/>"
    "<path d='M12 37 L12 47 L23 37 Z' fill='#5546E8'/>"
    "<text x='22' y='24' font-family='Arial' font-weight='800' font-size='17' fill='#fff' "
    "text-anchor='middle'>Z</text>"
    "<circle cx='16' cy='30' r='2.4' fill='#fff'/>"
    "<circle cx='22' cy='30' r='2.4' fill='#fff'/>"
    "<circle cx='28' cy='30' r='2.4' fill='#FFB020'/></svg>"
)
_MARCA = "Zappe <span style='color:#5546E8'>Hub</span><span style='color:#FFB020'>.</span>"


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
        "<svg viewBox='0 0 80 80' width='62' height='62' style='display:inline-block'>"
        "<rect x='8' y='10' width='64' height='56' rx='16' fill='#5546E8'/>"
        "<path d='M24 66 L24 80 L42 66 Z' fill='#5546E8'/>"
        "<text x='40' y='42' font-family='Arial' font-weight='800' font-size='28' fill='#fff' "
        "text-anchor='middle'>Z</text>"
        "<circle cx='29' cy='55' r='4' fill='#fff'/><circle cx='40' cy='55' r='4' fill='#fff'/>"
        "<circle cx='51' cy='55' r='4' fill='#FFB020'/></svg>"
        f"<h3 style='margin:10px 0 0'>{_MARCA}</h3></div>"
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
            "<link rel='icon' type='image/svg+xml' href='/favicon.svg'>"
            f"<title>Entrar &middot; Zappe Hub</title><style>{_CSS}</style>{corpo}</html>")
    return HTMLResponse(html)


@app.get("/entrar", response_class=HTMLResponse)
def entrar_form():
    return _pagina_login()


@app.post("/entrar")
def entrar(request: Request, usuario: str = Form(...), senha: str = Form(...)):
    # 1) usuario mestre (env) - SEMPRE admin e com PRIORIDADE, para nunca ficar
    #    trancado para fora mesmo que exista um usuario de equipe com o mesmo login.
    if (config.APP_PASSWORD and secrets.compare_digest(usuario.strip(), config.APP_USER)
            and secrets.compare_digest(senha, config.APP_PASSWORD)):
        request.session.update({"auth": True, "nome": config.APP_USER, "papel": "admin"})
        return RedirectResponse("/", status_code=303)
    # 2) usuarios da equipe (banco)
    u = usuarios.autenticar(usuario.strip(), senha)
    if u:
        request.session.update({"auth": True, "nome": u["nome"], "papel": u["papel"]})
        return RedirectResponse("/", status_code=303)
    return _pagina_login("Usuario ou senha incorretos.")


def _atual(request: Request) -> tuple[str, str]:
    """Nome e papel do usuario logado."""
    return request.session.get("nome", ""), request.session.get("papel", "atendente")


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


def _pagina(corpo: str, full: bool = False, ativo: str = "",
            papel: str = "", nome: str = "") -> HTMLResponse:
    def lk(href, label, key):
        return f"<a href='{href}' class='{'on' if ativo == key else ''}'>{label}</a>"
    # areas liberadas para todos os usuarios logados (admin + atendente)
    todos_extra = (lk("/produtos", "Produtos", "produtos")
                   + lk("/clientes", "Clientes", "clientes")
                   + lk("/balcao", "Balcao", "balcao"))
    admin_links = ""
    if papel == "admin":
        admin_links = (lk("/whatsapp", "WhatsApp", "whatsapp")
                       + lk("/resultado", "Resultado", "resultado")
                       + lk("/financeiro", "Financeiro", "financeiro")
                       + lk("/usuarios", "Equipe", "usuarios")
                       + lk("/desempenho", "Desempenho", "desempenho")
                       + lk("/backup", "Backup", "backup"))
    user_chip = (f"<span class='muted' style='font-size:12px;margin-right:4px'>"
                 f"<i class='ti ti-user'></i> {nome}</span>" if nome else "")
    nav = (
        "<div class='nav'>"
        f"<a class='brand' href='/'>{_ICONE}<span>{_MARCA}</span></a>"
        "<div class='links' style='display:flex;align-items:center'>"
        + lk("/inbox", "Caixa de entrada", "inbox")
        + lk("/perguntas", "Perguntas", "perguntas")
        + lk("/vendas?atend=__none__", "Pedidos", "vendas")
        + todos_extra
        + admin_links
        + user_chip
        + ("<a href='/sair'>Sair</a>" if config.APP_PASSWORD else "")
        + "</div></div>"
    )
    miolo = corpo if full else f"<div class='wrap'>{corpo}</div>"
    html = (
        "<!doctype html><html lang='pt-br'><meta charset='utf-8'>"
        "<meta name='viewport' content='width=device-width, initial-scale=1'>"
        "<link rel='icon' type='image/svg+xml' href='/favicon.svg'>"
        f"<title>Zappe Hub</title><style>{_CSS}</style>{nav}{miolo}</html>"
    )
    return HTMLResponse(html)


@app.get("/favicon.svg")
def favicon():
    return FileResponse(config.BASE_DIR / "zappehub-icone.svg", media_type="image/svg+xml")


@app.get("/logo.png")
def logo():
    return FileResponse(config.BASE_DIR / "helloow-logo.png")


_LANDING = """<!doctype html><html lang="pt-br"><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<link rel="icon" type="image/svg+xml" href="/favicon.svg">
<title>Zappe Hub - atendimento unificado para marketplaces</title>
<style>
*{box-sizing:border-box;margin:0;padding:0}
body{font-family:-apple-system,Segoe UI,Roboto,system-ui,sans-serif;color:#1E2330;background:#fff;line-height:1.6}
a{text-decoration:none;color:inherit}
.wrap{max-width:1000px;margin:0 auto;padding:0 20px}
.btn{display:inline-block;background:#5546E8;color:#fff;padding:12px 22px;border-radius:10px;font-weight:600;font-size:15px}
.btn.ghost{background:#fff;color:#5546E8;border:1px solid #d7d4f5}
header{border-bottom:1px solid #eef0f2;position:sticky;top:0;background:#fff;z-index:5}
header .wrap{display:flex;align-items:center;justify-content:space-between;padding:14px 20px}
.brand{display:flex;align-items:center;gap:9px;font-weight:700;font-size:18px}
.hero{background:#f3f1fe;padding:64px 0 56px;text-align:center}
.hero h1{font-size:40px;line-height:1.15;letter-spacing:-1px;max-width:760px;margin:0 auto 16px}
.hero h1 span{color:#5546E8}
.hero p{font-size:18px;color:#5b6573;max-width:620px;margin:0 auto 26px}
.dot{color:#FFB020}
section{padding:54px 0}
h2{font-size:28px;text-align:center;margin-bottom:8px;letter-spacing:-0.5px}
.sub{text-align:center;color:#8a93a0;margin-bottom:34px}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(240px,1fr));gap:18px}
.feat{border:1px solid #eef0f2;border-radius:14px;padding:22px}
.feat .ic{width:42px;height:42px;border-radius:11px;background:#f3f1fe;color:#5546E8;display:flex;align-items:center;justify-content:center;font-size:22px;margin-bottom:12px}
.feat h3{font-size:17px;margin-bottom:5px}
.feat p{color:#6b7280;font-size:14px}
.planos{display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:16px}
.plano{border:1px solid #e6e8eb;border-radius:16px;padding:24px 20px;text-align:center}
.plano.top{border:2px solid #5546E8;position:relative}
.tag{position:absolute;top:-12px;left:50%;transform:translateX(-50%);background:#5546E8;color:#fff;font-size:12px;padding:3px 14px;border-radius:999px}
.plano .nm{font-weight:700;font-size:18px}
.plano .at{color:#8a93a0;font-size:14px;margin:4px 0 12px}
.plano .pr{font-size:30px;font-weight:800}
.plano .pr small{font-size:14px;color:#8a93a0;font-weight:400}
.ctaband{background:#1E2330;color:#fff;text-align:center;border-radius:18px;padding:44px 20px;margin:10px 0 50px}
.ctaband h2{color:#fff}.ctaband p{color:#c7c9d1;margin-bottom:22px}
footer{border-top:1px solid #eef0f2;padding:26px 0;color:#8a93a0;font-size:13px;text-align:center}
@media(max-width:640px){.hero h1{font-size:30px}}
</style>

<header><div class="wrap">
  <a class="brand" href="/">
    <svg viewBox="0 0 44 50" width="30" height="34" aria-hidden="true">
      <rect x="3" y="3" width="38" height="34" rx="9" fill="#5546E8"/>
      <path d="M12 37 L12 47 L23 37 Z" fill="#5546E8"/>
      <text x="22" y="24" font-family="Arial" font-weight="800" font-size="17" fill="#fff" text-anchor="middle">Z</text>
      <circle cx="16" cy="30" r="2.4" fill="#fff"/><circle cx="22" cy="30" r="2.4" fill="#fff"/><circle cx="28" cy="30" r="2.4" fill="#FFB020"/>
    </svg>
    <span>Zappe <span style="color:#5546E8">Hub</span><span class="dot">.</span></span>
  </a>
  <a class="btn" href="/entrar">Entrar</a>
</div></header>

<div class="hero"><div class="wrap">
  <h1>Todos os seus marketplaces, <span>uma conversa só</span>.</h1>
  <p>Pre-venda e pos-venda do Mercado Livre num so lugar: responda as <b>perguntas do anuncio</b> e as <b>mensagens do cliente</b> apos a compra &mdash; com categorias, equipe e relatorios. Atenda mais rapido, sem trocar de aba.</p>
  <a class="btn" href="/entrar">Comecar agora</a>
</div></div>

<section><div class="wrap">
  <h2>Pre-venda e pos-venda, num so lugar</h2>
  <p class="sub">Todo o ciclo do atendimento no marketplace, integrado.</p>
  <div class="grid" style="grid-template-columns:1fr 1fr">
    <div class="feat"><div class="ic"><i class="ti ti-help-circle"></i></div><h3>Pre-venda &mdash; Perguntas do anuncio</h3><p>Responda as duvidas de quem ainda <b>nao comprou</b>, direto das perguntas do anuncio. Resposta rapida = mais vendas.</p></div>
    <div class="feat"><div class="ic"><i class="ti ti-messages"></i></div><h3>Pos-venda &mdash; Contato com o cliente</h3><p>Mensagens <b>apos a compra</b>: duvidas, a arte enviada pelo cliente e o status do pedido. Tudo organizado por loja e categoria.</p></div>
  </div>
</div></section>

<section style="background:#f6f7f9"><div class="wrap">
  <h2>Tudo o que o seu atendimento precisa</h2>
  <p class="sub">Pos-venda e pre-venda, varias contas, organizado e com a sua equipe.</p>
  <div class="grid">
    <div class="feat"><div class="ic"><i class="ti ti-messages"></i></div><h3>Caixa unificada</h3><p>Mensagens de varias contas do Mercado Livre num lugar so, com a arte enviada pelo cliente.</p></div>
    <div class="feat"><div class="ic"><i class="ti ti-help-circle"></i></div><h3>Perguntas do anuncio</h3><p>Responda a pre-venda (perguntas no anuncio) sem sair do hub.</p></div>
    <div class="feat"><div class="ic"><i class="ti ti-tags"></i></div><h3>Categorias e filtros</h3><p>Organize por tipo, loja e veja so as nao respondidas.</p></div>
    <div class="feat"><div class="ic"><i class="ti ti-search"></i></div><h3>Busca por codigo</h3><p>Ache qualquer pedido na hora pelo codigo, cliente ou produto.</p></div>
    <div class="feat"><div class="ic"><i class="ti ti-users"></i></div><h3>Equipe e papeis</h3><p>Cada atendente com seu login. Admin controla tudo.</p></div>
    <div class="feat"><div class="ic"><i class="ti ti-chart-bar"></i></div><h3>Desempenho</h3><p>Veja quem atendeu o que e quanto cada um respondeu.</p></div>
  </div>
</div></section>

<section><div class="wrap">
  <h2>Planos para cada tamanho de equipe</h2>
  <p class="sub">Escolha pelo numero de atendentes. Comece pequeno e cresca quando precisar.</p>
  <div style="text-align:center;margin:-12px 0 26px"><span style="background:#FFF1CC;color:#854F0B;font-size:14px;font-weight:600;padding:8px 18px;border-radius:999px;display:inline-flex;align-items:center;gap:8px"><i class="ti ti-rocket"></i> Precos especiais de lancamento &mdash; somente neste mes</span></div>
  <div class="planos">
    <div class="plano"><div class="nm">Essencial</div><div class="at">ate 3 atendentes</div><div class="pr">R$ 199<small>/mes</small></div></div>
    <div class="plano top"><div class="tag">Mais popular</div><div class="nm">Profissional</div><div class="at">ate 10 atendentes</div><div class="pr">R$ 299<small>/mes</small></div></div>
    <div class="plano"><div class="nm">Avancado</div><div class="at">ate 20 atendentes</div><div class="pr">R$ 399<small>/mes</small></div></div>
    <div class="plano"><div class="nm">Empresarial</div><div class="at">ate 50 atendentes</div><div class="pr">R$ 599<small>/mes</small></div></div>
  </div>
</div></section>

<section><div class="wrap"><div class="ctaband">
  <h2>Pronto para unificar seu atendimento?</h2>
  <p>Centralize Mercado Livre, organize sua equipe e atenda mais rapido.</p>
  <a class="btn ghost" href="/entrar">Entrar no Zappe Hub</a>
</div></div></section>

<footer>Zappe Hub &middot; atendimento unificado para marketplaces &middot; feito no Brasil</footer>
<link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/@tabler/icons-webfont@3.11.0/dist/tabler-icons.min.css">
</html>"""


@app.get("/", response_class=HTMLResponse)
def home(request: Request):
    # visitante (nao logado) ve a landing comercial; logado ve o painel
    if config.APP_PASSWORD and not request.session.get("auth"):
        return HTMLResponse(_LANDING)
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

    nome, papel = _atual(request)
    corpo = (
        f"<h1 style='margin-bottom:2px'>{_MARCA}</h1>"
        "<p class='muted' style='margin-top:0'>Gráfica Betinho</p>"
        + destaque
        + "<div class='card'><h3>Conexoes</h3>" + b + m + "</div>"
    )
    return _pagina(corpo, papel=papel, nome=nome)


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
def pedidos(request: Request, pagina: int = 1):
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
    nome, papel = _atual(request)
    return _pagina(corpo, ativo="pedidos", papel=papel, nome=nome)


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


# situacao do ENVIO (Mercado Livre): entregue x nao entregue x a enviar...
_ENVIO_BADGE = {
    "pending": ("A enviar", "#C77700", "#FCF1DD"),
    "ready_to_ship": ("A enviar", "#C77700", "#FCF1DD"),
    "handling": ("A enviar", "#C77700", "#FCF1DD"),
    "shipped": ("Enviado", "#0C447C", "#E6F1FB"),
    "delivered": ("Entregue", "#0F6E56", "#E1F5EE"),
    "not_delivered": ("Nao entregue", "#A32D2D", "#FCEBEB"),
    "cancelled": ("Cancelado", "#8a93a0", "#EEF0F2"),
}
# grupos usados no filtro de situacao
_ENVIO_GRUPO = {
    "a_enviar": {"pending", "ready_to_ship", "handling"},
    "enviado": {"shipped"},
    "entregue": {"delivered"},
    "nao_entregue": {"not_delivered"},
}


def _badge_envio(status: str) -> str:
    v = _ENVIO_BADGE.get(status)
    if not v:
        return ""
    rot, fg, bg = v
    return f"<span class='badge' style='color:{fg};background:{bg}'>{rot}</span>"


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


def _rail(cats: list, cat_atual: str, lojas: list, loja_atual: str, status_atual: str) -> str:
    def q(**over):
        params = {"loja": loja_atual, "cat": cat_atual, "status": status_atual}
        params.update(over)
        qs = "&".join(f"{k}={v}" for k, v in params.items() if v)
        return "/inbox" + ("?" + qs if qs else "")

    def link(label, href, ativo, icone, cor=None):
        cls = "chan" + (" on" if ativo else "")
        ponto = (f"<span class='dot' style='background:{cor}'></span>" if cor
                 else f"<i class='ti {icone}' style='font-size:15px'></i>")
        return f"<a class='{cls}' href='{href}'>{ponto}<span style='flex:1'>{label}</span></a>"

    # FILTROS
    filtros = "<div class='muted' style='padding:4px 11px 6px;font-size:11px'>FILTROS</div>"
    filtros += link("Nao respondidas", q(status="aguardando"),
                    status_atual == "aguardando", "ti-bell")

    # LOJAS
    lojas_html = "<div class='muted' style='padding:14px 11px 6px;font-size:11px'>LOJAS</div>"
    lojas_html += link("Todas as lojas", q(loja=""), loja_atual == "", "ti-building-store")
    for uid, nome in lojas:
        lojas_html += link(nome, q(loja=uid), loja_atual == uid, "ti-building-store")

    # CATEGORIAS
    cats_html = "<div class='muted' style='padding:14px 11px 6px;font-size:11px'>CATEGORIAS</div>"
    cats_html += link("Todas", q(cat=""), cat_atual == "", "ti-stack")
    for c in cats:
        cats_html += link(c["nome"], q(cat=str(c["id"])), cat_atual == str(c["id"]), "ti-tag")
    cats_html += link("Sem categoria", q(cat="none"), cat_atual == "none", "ti-tag-off")
    cats_html += ("<a class='chan' href='/categorias' style='color:#534AB7'>"
                  "<i class='ti ti-settings' style='font-size:15px'></i>"
                  "<span style='flex:1'>Gerenciar</span></a>")

    return "<div class='rail'>" + filtros + lojas_html + cats_html + "</div>"


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
  // ao navegar (clicar numa conversa/filtro) ou enviar um form, PARA o auto-refresh
  // para nao cancelar a navegacao -> resolve o "cancela, aperta de novo"
  var navegando=false;
  document.addEventListener('click',function(e){ if(e.target.closest('a')) navegando=true; },true);
  document.addEventListener('submit',function(){ navegando=true; },true);
  // auto-atualiza a cada 45s, mas NAO enquanto digita, arrasta ou navega
  setInterval(function(){
    if(navegando||drag)return;
    var inp=document.querySelector('.reply input[name=texto]');
    if(inp&&(inp.value.trim()!==''||document.activeElement===inp))return;
    var busca=document.querySelector('.clist input[name=q]');
    if(busca&&document.activeElement===busca)return;
    if(document.hidden)return;
    location.reload();
  },45000);
})();
</script>
"""


def _conv_dict(o: dict, uid: str, marcas: dict, aguardando: set) -> dict:
    pk = str(o.get("pack_id") or o.get("id"))
    produtos = o.get("order_items") or []
    return {
        "o": o, "pk": pk, "uid": uid,
        "codigo": str(o.get("id") or pk),
        "comprador": (o.get("buyer") or {}).get("nickname", "-"),
        "comprador_id": str((o.get("buyer") or {}).get("id", "")),
        "titulo": (produtos[0].get("item") or {}).get("title", "-") if produtos else "-",
        "data": str(o.get("date_created") or ""),
        "cat_id": marcas.get(pk),
        "aguarda": pk in aguardando,
    }


@app.get("/inbox", response_class=HTMLResponse)
def inbox(request: Request, pack: str = "", buyer: str = "", conta: str = "",
          cat: str = "", loja: str = "", status: str = "", q: str = "", pag: int = 1):
    contas = mercadolivre.contas()
    if not contas:
        return RedirectResponse("/ml/login")
    pag = max(1, pag)

    cats = categorias.listar_categorias()
    nomes_cat = {c["id"]: c["nome"] for c in cats}
    marcas = categorias.marcas()  # pack -> categoria_id
    lojas = [(str(a["user_id"]), mercadolivre.nome_exibicao(a)) for a in contas]
    apelidos = dict(lojas)

    # packs aguardando resposta (mensagens nao lidas)
    aguardando = set()
    for acc in contas:
        try:
            aguardando |= mercadolivre.packs_aguardando(str(acc["user_id"]), token=acc)
        except (RuntimeError, httpx.HTTPStatusError):
            pass

    # ---- coleta todas as conversas (todas as contas) ----
    convs = []
    selecionado = None
    sel_conta = None
    tem_mais = False
    for acc in contas:
        uid = str(acc["user_id"])
        try:
            pedidos = mercadolivre.listar_pedidos(limite=15, user_id=uid, token=acc, pagina=pag)
        except (RuntimeError, httpx.HTTPStatusError):
            pedidos = []
        if len(pedidos) >= 15:
            tem_mais = True
        for o in pedidos:
            convs.append(_conv_dict(o, uid, marcas, aguardando))

    # busca por codigo antigo (que nao esta na lista recente): consulta direto no ML
    termo = q.strip()
    if termo.isdigit() and not any(c["codigo"] == termo or c["pk"] == termo for c in convs):
        o, uid_found = mercadolivre.buscar_pedido_cod(termo, contas)
        if o:
            convs.append(_conv_dict(o, uid_found, marcas, aguardando))

    # identifica a conversa selecionada
    for c in convs:
        if c["pk"] == pack and c["uid"] == conta:
            selecionado = c["o"]
            sel_conta = next((a for a in contas if str(a["user_id"]) == conta), None)
            break
    # se a conversa aberta nao esta na pagina atual, busca direto (sempre abre).
    # o codigo pode ser de pedido OU de pacote (carrinho).
    if selecionado is None and pack and conta:
        acc = next((a for a in contas if str(a["user_id"]) == conta), None)
        if acc:
            o = mercadolivre.obter_pedido(pack, token=acc) or mercadolivre.pedido_do_pack(pack, token=acc)
            if o:
                selecionado, sel_conta = o, acc

    # ordena: conversas aguardando primeiro, depois pelas mais recentes
    convs.sort(key=lambda c: (c["aguarda"], c["data"]), reverse=True)

    termo_l = termo.lower()

    # ---- aplica filtros e monta a lista ----
    itens = ""
    for c in convs:
        if termo:  # busca tem prioridade sobre os outros filtros
            alvo = f"{c['codigo']} {c['pk']} {c['comprador']} {c['titulo']}".lower()
            if termo_l not in alvo:
                continue
        else:
            if loja and c["uid"] != loja:
                continue
            if status == "aguardando" and not c["aguarda"]:
                continue
            if cat == "none" and c["cat_id"]:
                continue
            if cat and cat != "none" and str(c["cat_id"]) != cat:
                continue
        on = c["pk"] == pack and c["uid"] == conta
        cat_nome = nomes_cat.get(c["cat_id"]) if c["cat_id"] else None
        etiqueta = (f"<div style='margin-top:5px'><span class='badge' "
                    f"style='background:#EEEDFE;color:#3C3489'>{cat_nome}</span></div>"
                    if cat_nome else "")
        sino = ("<span style='background:#FFB020;width:8px;height:8px;border-radius:50%;"
                "flex:none;display:inline-block' title='Aguardando resposta'></span>"
                if c["aguarda"] else "")
        itens += (
            f"<a class='ci {'on' if on else ''}' "
            f"href='/inbox?pack={c['pk']}&buyer={c['comprador_id']}&conta={c['uid']}"
            f"&cat={cat}&loja={loja}&status={status}&q={q}&pag={pag}'>"
            "<div class='top'>"
            f"<span class='nm' style='display:flex;align-items:center;gap:6px'>{sino}{c['comprador']}</span>"
            f"<span class='badge' style='background:#FFF7CC;color:#7a6a00'>{apelidos.get(c['uid'])}</span>"
            "</div>"
            f"<div class='pv'>{c['titulo']}</div>"
            f"<div class='muted' style='font-size:11px;margin-top:3px'>"
            f"<i class='ti ti-hash' style='font-size:12px'></i> {c['codigo']}</div>"
            f"{etiqueta}</a>"
        )
    if not itens:
        vazio = "Nenhum resultado para a busca." if termo else "Nenhuma conversa com esses filtros."
        itens = f"<div style='padding:16px' class='muted'>{vazio}</div>"

    # barra de busca no topo da lista
    busca = (
        "<form method='get' action='/inbox' "
        "style='padding:9px 10px;border-bottom:1px solid #e6e8eb;display:flex;gap:6px;"
        "position:sticky;top:0;background:#fafbfc;z-index:2'>"
        f"<input name='q' value='{q}' placeholder='Buscar por codigo, cliente ou produto' "
        "style='flex:1;padding:8px 10px;border:1px solid #d7dade;border-radius:8px;font-size:13px'/>"
        f"<input type='hidden' name='cat' value='{cat}'/>"
        f"<input type='hidden' name='loja' value='{loja}'/>"
        f"<input type='hidden' name='status' value='{status}'/>"
        "<button class='btn ghost' style='padding:0 12px'><i class='ti ti-search'></i></button>"
        + (f"<a class='btn ghost' href='/inbox' style='padding:8px 10px' "
           "title='Limpar busca'><i class='ti ti-x'></i></a>" if termo else "")
        + "</form>"
    )

    # navegacao de paginas (so quando nao esta buscando)
    nav = ""
    if not termo:
        base = f"/inbox?cat={cat}&loja={loja}&status={status}"
        partes = []
        if pag > 1:
            partes.append(f"<a class='btn ghost' href='{base}&pag={pag - 1}'>&larr; Recentes</a>")
        partes.append(f"<span class='muted' style='font-size:12px'>Pagina {pag}</span>")
        if tem_mais:
            partes.append(f"<a class='btn ghost' href='{base}&pag={pag + 1}'>Mais antigas &rarr;</a>")
        nav = ("<div style='padding:12px;display:flex;gap:8px;align-items:center;"
               "justify-content:center;border-top:1px solid #eef0f2'>" + "".join(partes) + "</div>")

    itens = busca + itens + nav

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
            mensagens = mercadolivre.listar_mensagens(pack, user_id=conta, token=sel_conta)
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
            f"<input type='hidden' name='loja' value='{loja}'/>"
            f"<input type='hidden' name='status' value='{status}'/>"
            f"<input type='hidden' name='q' value='{q}'/>"
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
            f"<span title='Codigo do pedido no Mercado Livre / Bling'>"
            f"<i class='ti ti-hash'></i> {selecionado.get('id', pack)}</span>"
            f"{seletor}</div>"
            f"<div class='thread'>{baloes}</div>"
            f"<form class='reply' method='post' action='/inbox/responder'>"
            f"<input type='hidden' name='pack' value='{pack}'/>"
            f"<input type='hidden' name='buyer' value='{buyer}'/>"
            f"<input type='hidden' name='conta' value='{conta}'/>"
            f"<input type='hidden' name='cat' value='{cat}'/>"
            f"<input type='hidden' name='loja' value='{loja}'/>"
            f"<input type='hidden' name='status' value='{status}'/>"
            f"<input type='hidden' name='q' value='{q}'/>"
            "<input name='texto' placeholder='Responder o comprador...' required/>"
            "<button class='btn ml' type='submit'>Enviar</button></form>"
        )

    corpo = (
        "<link rel='stylesheet' href='https://cdn.jsdelivr.net/npm/"
        "@tabler/icons-webfont@3.11.0/dist/tabler-icons.min.css'>"
        "<div class='inbox'>"
        + _rail(cats, cat, lojas, loja, status)
        + f"<div class='clist'>{itens}</div>"
        + "<div class='splitter' id='split'></div>"
        + f"<div class='detail'>{detalhe}</div>"
        + "</div>"
        + _SPLIT_JS
    )
    nome, papel = _atual(request)
    return _pagina(corpo, full=True, ativo="inbox", papel=papel, nome=nome)


@app.post("/inbox/responder")
def inbox_responder(request: Request, pack: str = Form(...), buyer: str = Form(""),
                    conta: str = Form(""), cat: str = Form(""), loja: str = Form(""),
                    status: str = Form(""), q: str = Form(""), texto: str = Form(...)):
    try:
        mercadolivre.enviar_mensagem(pack, buyer, texto, user_id=conta or None)
        nome, _ = _atual(request)
        usuarios.registrar(nome, "Respondeu mensagem", f"pedido {pack}")
    except (RuntimeError, httpx.HTTPStatusError):
        pass
    return RedirectResponse(
        f"/inbox?pack={pack}&buyer={buyer}&conta={conta}&cat={cat}&loja={loja}&status={status}&q={q}",
        status_code=303)


@app.get("/ml/anexo/{conta}/{filename:path}")
def ml_anexo(conta: str, filename: str):
    """Baixa e serve um anexo (arte) de uma mensagem do Mercado Livre."""
    try:
        conteudo, ctype = mercadolivre.baixar_anexo(filename, user_id=conta)
    except Exception:
        return Response(status_code=404)
    return Response(content=conteudo, media_type=ctype)


# =========================================================================== #
# Perguntas (pre-venda, no anuncio)
# =========================================================================== #
@app.get("/perguntas", response_class=HTMLResponse)
def perguntas(request: Request, status: str = "unanswered"):
    contas = mercadolivre.contas()
    if not contas:
        return RedirectResponse("/ml/login")

    cards = ""
    for acc in contas:
        uid = str(acc["user_id"])
        apelido = mercadolivre.nome_exibicao(acc)
        try:
            lista = mercadolivre.listar_perguntas(user_id=uid, token=acc, status=status)
        except (RuntimeError, httpx.HTTPStatusError):
            lista = []
        for qd in lista:
            item_id = qd.get("item_id")
            titulo = mercadolivre.titulo_item(item_id, user_id=uid, token=acc)
            texto = (qd.get("text") or "").replace("<", "&lt;")
            data = _data_br(qd.get("date_created"))
            qid = qd.get("id")
            ans = qd.get("answer") or {}
            if ans.get("text"):
                rodape = ("<div style='margin-top:8px;background:#E1F5EE;border-radius:8px;"
                          "padding:8px 10px;font-size:13px'><b>Sua resposta:</b> "
                          f"{(ans.get('text') or '').replace('<', '&lt;')}</div>")
            else:
                rodape = (
                    "<form method='post' action='/perguntas/responder' "
                    "style='display:flex;gap:8px;margin-top:10px'>"
                    f"<input type='hidden' name='qid' value='{qid}'/>"
                    f"<input type='hidden' name='conta' value='{uid}'/>"
                    f"<input type='hidden' name='status' value='{status}'/>"
                    "<input name='texto' placeholder='Responder a pergunta...' required "
                    "style='flex:1;padding:9px;border:1px solid #d7dade;border-radius:8px'/>"
                    "<button class='btn ml'>Responder</button></form>"
                )
            cards += (
                "<div class='card'>"
                "<div style='display:flex;justify-content:space-between;gap:8px'>"
                f"<span class='muted' style='font-size:12px'><i class='ti ti-package'></i> {titulo}</span>"
                f"<span class='badge' style='background:#FFF7CC;color:#7a6a00'>{apelido}</span></div>"
                f"<div style='font-size:15px;margin:8px 0 4px'>{texto}</div>"
                f"<div class='muted' style='font-size:12px'>{data}</div>"
                f"{rodape}</div>"
            )
    if not cards:
        cards = "<p class='muted'>Nenhuma pergunta aqui.</p>"

    def tg(label, val):
        cls = "btn ml" if status == val else "btn ghost"
        return f"<a class='{cls}' href='/perguntas?status={val}'>{label}</a>"

    topo = ("<div style='display:flex;gap:8px;margin-bottom:14px;flex-wrap:wrap'>"
            + tg("Nao respondidas", "unanswered") + tg("Respondidas", "answered")
            + tg("Todas", "all") + "</div>")
    corpo = ("<link rel='stylesheet' href='https://cdn.jsdelivr.net/npm/"
             "@tabler/icons-webfont@3.11.0/dist/tabler-icons.min.css'>"
             "<h1>Perguntas <span class='muted' style='font-size:14px'>(pre-venda)</span></h1>"
             f"{topo}{cards}")
    nome, papel = _atual(request)
    return _pagina(corpo, ativo="perguntas", papel=papel, nome=nome)


@app.post("/perguntas/responder")
def perguntas_responder(request: Request, qid: str = Form(...), conta: str = Form(""),
                        status: str = Form("unanswered"), texto: str = Form(...)):
    try:
        mercadolivre.responder_pergunta(qid, texto, user_id=conta or None)
        nome, _ = _atual(request)
        usuarios.registrar(nome, "Respondeu pergunta", f"pergunta {qid}")
    except (RuntimeError, httpx.HTTPStatusError):
        pass
    return RedirectResponse(f"/perguntas?status={status}", status_code=303)


# =========================================================================== #
# Categorias (etiquetas das conversas)
# =========================================================================== #
@app.post("/categoria/marcar")
def categoria_marcar(pack: str = Form(...), conta: str = Form(""), buyer: str = Form(""),
                     cat: str = Form(""), loja: str = Form(""), status: str = Form(""),
                     q: str = Form(""), categoria: str = Form("")):
    categorias.marcar(pack, int(categoria) if categoria else None)
    return RedirectResponse(
        f"/inbox?pack={pack}&buyer={buyer}&conta={conta}&cat={cat}&loja={loja}&status={status}&q={q}",
        status_code=303)


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


# =========================================================================== #
# Equipe (usuarios) e Desempenho (log) - apenas admin
# =========================================================================== #
@app.get("/usuarios", response_class=HTMLResponse)
def usuarios_page(request: Request):
    nome, papel = _atual(request)
    if papel != "admin":
        return RedirectResponse("/inbox")
    linhas = ""
    for u in usuarios.listar_usuarios():
        linhas += (
            "<div style='display:flex;justify-content:space-between;align-items:center;"
            "border-bottom:1px solid #eef0f2;padding:8px 0'>"
            f"<div><b>{u['nome']}</b> <span class='muted'>({u['usuario']})</span> "
            f"<span class='badge' style='background:#EEEDFE;color:#3C3489'>{u['papel']}</span></div>"
            "<form method='post' action='/usuarios/excluir' "
            "onsubmit=\"return confirm('Remover usuario?')\">"
            f"<input type='hidden' name='id' value='{u['id']}'/>"
            "<button class='btn' style='background:#FCEBEB;color:#A32D2D'>Remover</button>"
            "</form></div>"
        )
    if not linhas:
        linhas = "<p class='muted'>Nenhum usuario cadastrado ainda.</p>"
    corpo = (
        "<h1>Equipe</h1>"
        "<div class='card'><h3>Adicionar usuario</h3>"
        "<form method='post' action='/usuarios/criar' style='display:grid;gap:8px;max-width:420px'>"
        "<input name='nome' placeholder='Nome (ex: Maria)' required "
        "style='padding:9px;border:1px solid #d7dade;border-radius:8px'/>"
        "<input name='usuario' placeholder='Login (ex: maria)' required "
        "style='padding:9px;border:1px solid #d7dade;border-radius:8px'/>"
        "<input name='senha' type='password' placeholder='Senha' required "
        "style='padding:9px;border:1px solid #d7dade;border-radius:8px'/>"
        "<select name='papel' style='padding:9px;border:1px solid #d7dade;border-radius:8px'>"
        "<option value='atendente'>Atendente</option>"
        "<option value='admin'>Administrador</option></select>"
        "<button class='btn'>Adicionar</button></form></div>"
        f"<div class='card'><h3>Usuarios</h3>{linhas}</div>"
        "<p class='muted'>O login mestre (Diego) continua sempre valendo como admin.</p>"
    )
    return _pagina(corpo, ativo="usuarios", papel=papel, nome=nome)


@app.post("/usuarios/criar")
def usuarios_criar(request: Request, nome: str = Form(...), usuario: str = Form(...),
                   senha: str = Form(...), papel: str = Form("atendente")):
    if _atual(request)[1] != "admin":
        return RedirectResponse("/inbox")
    usuarios.criar_usuario(nome.strip(), usuario.strip(), senha, papel)
    return RedirectResponse("/usuarios", status_code=303)


@app.post("/usuarios/excluir")
def usuarios_excluir(request: Request, id: int = Form(...)):
    if _atual(request)[1] != "admin":
        return RedirectResponse("/inbox")
    usuarios.excluir_usuario(id)
    return RedirectResponse("/usuarios", status_code=303)


@app.get("/desempenho", response_class=HTMLResponse)
def desempenho(request: Request, periodo: str = "tudo", de: str = "", ate: str = ""):
    nome, papel = _atual(request)
    if papel != "admin":
        return RedirectResponse("/inbox")
    hoje = date.today()
    if periodo == "hoje":
        d_de = d_ate = hoje.isoformat()
    elif periodo == "semana":
        d_de, d_ate = (hoje - timedelta(days=6)).isoformat(), hoje.isoformat()
    elif periodo == "mes":
        d_de, d_ate = hoje.replace(day=1).isoformat(), hoje.isoformat()
    elif periodo == "custom" and de and ate:
        d_de, d_ate = de, ate
    else:
        periodo, d_de, d_ate = "tudo", None, None

    def _pill(label, val):
        on = ("background:#2D3277;color:#fff" if periodo == val
              else "background:#fff;border:1px solid #d7dade;color:#333")
        return (f"<a href='/desempenho?periodo={val}' style='padding:7px 14px;border-radius:8px;"
                f"font-size:13px;text-decoration:none;{on}'>{label}</a>")

    filtro = (
        "<div style='display:flex;gap:8px;align-items:center;flex-wrap:wrap;margin:6px 0 6px'>"
        + _pill("Hoje", "hoje") + _pill("7 dias", "semana") + _pill("Este mes", "mes")
        + _pill("Tudo", "tudo")
        + "<form method='get' action='/desempenho' style='display:flex;gap:6px;align-items:center;"
        "margin-left:6px'><input type='hidden' name='periodo' value='custom'/>"
        f"<input type='date' name='de' value='{de or (d_de or '')}' "
        "style='padding:7px;border:1px solid #d7dade;border-radius:8px'/>"
        f"<input type='date' name='ate' value='{ate or (d_ate or '')}' "
        "style='padding:7px;border:1px solid #d7dade;border-radius:8px'/>"
        "<button class='btn ghost' style='padding:6px 12px'>Aplicar</button></form></div>"
        + (f"<p class='muted' style='font-size:13px'>Periodo: {_data_br(d_de)} a {_data_br(d_ate)}</p>"
           if d_de else "<p class='muted' style='font-size:13px'>Todo o periodo.</p>")
    )

    res = usuarios.resumo(d_de, d_ate)
    if res:
        cards = "<div style='display:flex;gap:10px;flex-wrap:wrap;margin:10px 0 22px'>"
        for r in res:
            cards += (f"<div style='background:#f4f5f7;border-radius:10px;padding:12px 18px'>"
                      f"<div class='muted' style='font-size:12px'>{r['usuario'] or '-'}</div>"
                      f"<div style='font-size:22px;font-weight:600'>{r['total']}</div>"
                      "<div class='muted' style='font-size:11px'>atendimentos</div></div>")
        cards += "</div>"
    else:
        cards = "<p class='muted'>Sem atividade registrada ainda.</p>"

    linhas = ""
    for l in usuarios.listar_log(200, d_de, d_ate):
        try:
            quando = l["ts"].strftime("%d/%m/%Y %H:%M")
        except Exception:
            quando = str(l["ts"])
        linhas += (f"<tr><td>{quando}</td><td>{l['usuario'] or '-'}</td>"
                   f"<td>{l['acao']}</td><td>{l['alvo']}</td></tr>")
    if not linhas:
        linhas = "<tr><td colspan='4' class='muted'>Sem registros ainda.</td></tr>"

    corpo = (
        "<h1>Desempenho</h1>"
        f"{filtro}"
        "<h3>Atendimentos por pessoa</h3>"
        f"{cards}"
        "<h3>Historico &mdash; quem atendeu o que</h3>"
        "<table><tr><th>Quando</th><th>Usuario</th><th>Acao</th><th>Alvo</th></tr>"
        f"{linhas}</table>"
    )
    return _pagina(corpo, ativo="desempenho", papel=papel, nome=nome)


# =========================================================================== #
# Resultado / Precificacao (valor liquido por pedido) - admin
# =========================================================================== #
def _num(s, padrao=0.0):
    try:
        return float(str(s).replace(",", ".").strip())
    except Exception:
        return padrao


def _moeda(v):
    return "R$ " + f"{v:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def _preco_cfg():
    c = store.carregar("preco_config") or {}
    return {
        "custo_pct": float(c.get("custo_pct", 20)),
        "imposto_pct": float(c.get("imposto_pct", 6)),
        "frete": float(c.get("frete", 0)),
        "definido": bool(c),
    }


@app.get("/resultado/config", response_class=HTMLResponse)
def resultado_config(request: Request):
    nome, papel = _atual(request)
    if papel != "admin":
        return RedirectResponse("/inbox")
    cfg = _preco_cfg()
    corpo = (
        "<h1>Configuracao de precificacao</h1>"
        "<p class='muted'>Preencha para calcular o valor liquido dos pedidos.</p>"
        "<div class='card' style='max-width:480px'>"
        "<form method='post' action='/resultado/config' style='display:grid;gap:16px'>"
        "<div><label style='font-size:13px;color:#5b6573'>% de custo medio sobre a venda</label>"
        f"<input name='custo_pct' value='{cfg['custo_pct']:g}' "
        "style='width:100%;padding:9px;border:1px solid #d7dade;border-radius:8px'/>"
        "<div class='muted' style='font-size:11px'>Ex: 20 = o produto custa 20% do valor da venda. "
        "Usado so para os produtos SEM custo preenchido na aba <a href='/produtos'>Produtos</a> "
        "(la voce poe o custo real de cada anuncio).</div></div>"
        "<div><label style='font-size:13px;color:#5b6573'>% de imposto sobre a venda</label>"
        f"<input name='imposto_pct' value='{cfg['imposto_pct']:g}' "
        "style='width:100%;padding:9px;border:1px solid #d7dade;border-radius:8px'/>"
        "<div class='muted' style='font-size:11px'>Ex: Simples Nacional ~6%.</div></div>"
        "<div><label style='font-size:13px;color:#5b6573'>Frete medio por pedido (R$)</label>"
        f"<input name='frete' value='{cfg['frete']:g}' "
        "style='width:100%;padding:9px;border:1px solid #d7dade;border-radius:8px'/>"
        "<div class='muted' style='font-size:11px'>Quanto voce paga de frete, em media. 0 se o cliente paga.</div></div>"
        "<button class='btn'>Salvar</button></form></div>"
        "<p style='margin-top:14px'><a href='/resultado'>&larr; ver o resultado</a></p>"
    )
    return _pagina(corpo, ativo="resultado", papel=papel, nome=nome)


@app.post("/resultado/config")
def resultado_config_salvar(request: Request, custo_pct: str = Form("20"),
                            imposto_pct: str = Form("6"), frete: str = Form("0")):
    if _atual(request)[1] != "admin":
        return RedirectResponse("/inbox")
    store.salvar("preco_config", {
        "custo_pct": _num(custo_pct, 20),
        "imposto_pct": _num(imposto_pct, 6),
        "frete": _num(frete, 0),
    })
    return RedirectResponse("/resultado", status_code=303)


def _calc_resultado(de: str, ate: str, cfg: dict):
    """Percorre os pedidos do periodo e devolve (linhas_html, totais, n_pedidos).
    Usado pela aba Resultado (tabela) e pelo Fechamento (so os totais)."""
    linhas = ""
    n = 0
    custos_prod = produtos.custos()  # {item_id: custo real} carregado 1x
    t = {"venda": 0.0, "com": 0.0, "frete": 0.0, "arec": 0.0,
         "custo": 0.0, "imp": 0.0, "liq": 0.0}
    for acc in mercadolivre.contas():
        uid = str(acc["user_id"])
        try:
            pedidos = mercadolivre.pedidos_periodo(de, ate, user_id=uid, token=acc)
        except (RuntimeError, httpx.HTTPStatusError):
            pedidos = []
        for o in pedidos:
            n += 1
            venda = float(o.get("total_amount") or 0)
            if not venda:
                venda = sum(float(it.get("unit_price") or 0) * float(it.get("quantity") or 0)
                            for it in (o.get("order_items") or []))
            comissao = sum(float(it.get("sale_fee") or 0) for it in (o.get("order_items") or []))
            frete = cfg["frete"]
            a_receber = venda - comissao - frete  # o que o ML deposita
            # custo: usa o custo REAL do produto (aba Produtos) quando preenchido;
            # senao, cai no % configurado para a parte daquele item.
            custo = 0.0
            for it in (o.get("order_items") or []):
                qtd = float(it.get("quantity") or 0)
                venda_it = float(it.get("unit_price") or 0) * qtd
                item_id = str((it.get("item") or {}).get("id") or "")
                real = custos_prod.get(item_id)
                custo += (real * qtd) if real is not None else (venda_it * cfg["custo_pct"] / 100)
            imposto = venda * cfg["imposto_pct"] / 100
            liquido = a_receber - custo - imposto
            margem = (liquido / venda * 100) if venda else 0
            t["venda"] += venda; t["com"] += comissao; t["frete"] += frete
            t["arec"] += a_receber; t["custo"] += custo; t["imp"] += imposto
            t["liq"] += liquido
            cor = "#0F6E56" if liquido >= 0 else "#A32D2D"
            itens_ped = o.get("order_items") or []
            titulo = (itens_ped[0].get("item") or {}).get("title", "-") if itens_ped else "-"
            linhas += (
                f"<tr><td>{_data_br(o.get('date_created'))}</td><td>{o.get('id','-')}</td>"
                f"<td>{titulo[:32]}</td><td>{_moeda(venda)}</td><td>{_moeda(comissao)}</td>"
                f"<td>{_moeda(frete)}</td><td style='font-weight:500'>{_moeda(a_receber)}</td>"
                f"<td>{_moeda(custo)}</td><td>{_moeda(imposto)}</td>"
                f"<td style='color:{cor};font-weight:500'>{_moeda(liquido)}</td>"
                f"<td style='color:{cor}'>{margem:.0f}%</td></tr>"
            )
    return linhas, t, n


@app.get("/resultado", response_class=HTMLResponse)
def resultado(request: Request, de: str = "", ate: str = ""):
    nome, papel = _atual(request)
    if papel != "admin":
        return RedirectResponse("/inbox")
    cfg = _preco_cfg()
    hoje = date.today()
    de = de or hoje.replace(day=1).isoformat()
    ate = ate or hoje.isoformat()

    linhas, t, n_pedidos = _calc_resultado(de, ate, cfg)
    t_venda, t_com, t_frete = t["venda"], t["com"], t["frete"]
    t_arec, t_custo, t_imp, t_liq = t["arec"], t["custo"], t["imp"], t["liq"]
    if not linhas:
        linhas = "<tr><td colspan='11' class='muted'>Nenhum pedido no periodo.</td></tr>"

    margem_media = (t_liq / t_venda * 100) if t_venda else 0
    cards = (
        "<div style='display:flex;gap:12px;flex-wrap:wrap;margin:12px 0 22px'>"
        f"<div style='background:#f4f5f7;border-radius:10px;padding:12px 18px'><div class='muted' style='font-size:12px'>Faturamento</div><div style='font-size:20px;font-weight:600'>{_moeda(t_venda)}</div></div>"
        f"<div style='background:#f4f5f7;border-radius:10px;padding:12px 18px'><div class='muted' style='font-size:12px'>A receber (ML)</div><div style='font-size:20px;font-weight:600'>{_moeda(t_arec)}</div></div>"
        f"<div style='background:#f4f5f7;border-radius:10px;padding:12px 18px'><div class='muted' style='font-size:12px'>Custos + taxas</div><div style='font-size:20px;font-weight:600'>{_moeda(t_com + t_frete + t_custo + t_imp)}</div></div>"
        f"<div style='background:#EEEDFE;border-radius:10px;padding:12px 18px'><div class='muted' style='font-size:12px'>Lucro liquido</div><div style='font-size:20px;font-weight:700;color:#3C3489'>{_moeda(t_liq)}</div></div>"
        f"<div style='background:#f4f5f7;border-radius:10px;padding:12px 18px'><div class='muted' style='font-size:12px'>Margem media</div><div style='font-size:20px;font-weight:600'>{margem_media:.0f}%</div></div>"
        "</div>"
    )
    aviso = ("" if cfg["definido"] else
             "<div class='card' style='background:#FFF7E6;border-color:#FAD89B'>"
             "Voce ainda nao configurou os percentuais &mdash; usando custo 20% e imposto 6% de exemplo. "
             "<a href='/resultado/config'>Configurar agora</a></div>")
    form_periodo = (
        "<form method='get' action='/resultado' "
        "style='display:flex;gap:8px;align-items:flex-end;flex-wrap:wrap;margin:6px 0 16px'>"
        "<div><div class='muted' style='font-size:12px'>De</div>"
        f"<input type='date' name='de' value='{de}' "
        "style='padding:8px;border:1px solid #d7dade;border-radius:8px'/></div>"
        "<div><div class='muted' style='font-size:12px'>Ate</div>"
        f"<input type='date' name='ate' value='{ate}' "
        "style='padding:8px;border:1px solid #d7dade;border-radius:8px'/></div>"
        "<button class='btn'>Filtrar</button></form>"
    )
    corpo = (
        "<h1>Resultado</h1>"
        f"<p class='muted'>Periodo {_data_br(de)} a {_data_br(ate)} &middot; "
        f"<b>{n_pedidos}</b> pedidos &middot; Custo {cfg['custo_pct']:g}% &middot; "
        f"Imposto {cfg['imposto_pct']:g}% &middot; Frete {_moeda(cfg['frete'])}/pedido &middot; "
        "<a href='/resultado/config'>ajustar</a></p>"
        f"{form_periodo}{aviso}{cards}"
        "<div style='overflow-x:auto'><table style='min-width:760px'>"
        "<tr><th>Data</th><th>Pedido</th><th>Produto</th><th>Venda</th><th>Comissao</th>"
        "<th>Frete</th><th>A receber</th><th>Custo</th><th>Imposto</th><th>Liquido</th>"
        f"<th>Margem</th></tr>{linhas}</table></div>"
        "<p class='muted' style='margin-top:12px;font-size:12px'>Venda e <b>comissao</b> = reais do "
        "Mercado Livre. <b>A receber</b> = venda &minus; comissao &minus; frete (o que cai na conta). "
        "Custo e imposto = % configurados; frete = medio configurado.</p>"
    )
    return _pagina(corpo, ativo="resultado", papel=papel, nome=nome)


# --------------------------------------------------------------------------- #
# Financeiro: contador de consumo de IA + custos fixos + fechamento do mes
# --------------------------------------------------------------------------- #
def _mes_br(ym: str) -> str:
    nomes = ["", "jan", "fev", "mar", "abr", "mai", "jun",
             "jul", "ago", "set", "out", "nov", "dez"]
    try:
        a, m = ym.split("-")
        return f"{nomes[int(m)]}/{a}"
    except Exception:
        return ym


@app.get("/financeiro", response_class=HTMLResponse)
def financeiro_page(request: Request):
    nome, papel = _atual(request)
    if papel != "admin":
        return RedirectResponse("/inbox")

    hoje = date.today()
    pl = ia_consumo.plano()
    res = ia_consumo.resumo_mes()
    cambio = pl["cambio"]
    custo_brl = res["custo_usd"] * cambio

    usados = res["total"]
    limite = max(1, pl["limite"])
    pct = min(100, usados / limite * 100)
    barra_cor = "#0F6E56" if pct < 80 else ("#C77700" if pct < 100 else "#A32D2D")

    # projecao linear do mes (com base no dia de hoje)
    dias_mes = calendar.monthrange(hoje.year, hoje.month)[1]
    proj = round(usados / hoje.day * dias_mes) if hoje.day else usados
    proj_brl = (custo_brl / hoje.day * dias_mes) if hoje.day else custo_brl

    pt = res["por_tipo"]
    n_texto = pt.get("texto", {}).get("n", 0)
    n_foto = pt.get("foto", {}).get("n", 0)
    c_texto = pt.get("texto", {}).get("custo_usd", 0.0) * cambio
    c_foto = pt.get("foto", {}).get("custo_usd", 0.0) * cambio

    # margem do pacote: o que voce cobra vs o que custa de verdade
    margem_reais = pl["preco_pacote"] - custo_brl
    margem_pct = (margem_reais / pl["preco_pacote"] * 100) if pl["preco_pacote"] else 0
    excedente_qtd = max(0, usados - limite)
    excedente_cobr = excedente_qtd * pl["excedente"]

    card_ia = (
        "<div class='card'>"
        "<div style='display:flex;justify-content:space-between;align-items:center'>"
        "<h3 style='margin:0'>&#129302; Consumo de IA &middot; "
        f"<span class='muted' style='font-weight:400'>{_mes_br(res['mes'])}</span></h3>"
        "<a class='muted' href='/financeiro/plano' style='font-size:13px'>ajustar plano</a></div>"
        f"<div style='display:flex;justify-content:space-between;margin:14px 0 6px'>"
        f"<b>{usados}</b> de {limite} interacoes incluidas"
        f"<span class='muted'>{pct:.0f}%</span></div>"
        "<div style='background:#e9ebef;border-radius:999px;height:12px;overflow:hidden'>"
        f"<div style='width:{pct:.0f}%;height:100%;background:{barra_cor}'></div></div>"
        "<div style='display:flex;gap:12px;flex-wrap:wrap;margin-top:16px'>"
        f"<div style='background:#f4f5f7;border-radius:10px;padding:12px 16px'>"
        f"<div class='muted' style='font-size:12px'>Custo real (sua conta API)</div>"
        f"<div style='font-size:20px;font-weight:600'>{_moeda(custo_brl)}</div></div>"
        f"<div style='background:#f4f5f7;border-radius:10px;padding:12px 16px'>"
        f"<div class='muted' style='font-size:12px'>Projecao do mes</div>"
        f"<div style='font-size:20px;font-weight:600'>{proj} int &middot; {_moeda(proj_brl)}</div></div>"
        f"<div style='background:#EEEDFE;border-radius:10px;padding:12px 16px'>"
        f"<div class='muted' style='font-size:12px'>Voce cobra (pacote)</div>"
        f"<div style='font-size:20px;font-weight:700;color:#3C3489'>{_moeda(pl['preco_pacote'])}</div></div>"
        f"<div style='background:#f4f5f7;border-radius:10px;padding:12px 16px'>"
        f"<div class='muted' style='font-size:12px'>Margem do pacote</div>"
        f"<div style='font-size:20px;font-weight:600;color:#0F6E56'>{_moeda(margem_reais)} "
        f"<span style='font-size:13px'>({margem_pct:.0f}%)</span></div></div>"
        "</div>"
        "<table style='margin-top:16px'>"
        "<tr><th>Tipo de interacao</th><th>Qtd</th><th>Custo (R$)</th></tr>"
        f"<tr><td>Analise (texto)</td><td>{n_texto}</td><td>{_moeda(c_texto)}</td></tr>"
        f"<tr><td>Leitura de boleto/nota (foto)</td><td>{n_foto}</td><td>{_moeda(c_foto)}</td></tr>"
        "</table>"
        + (f"<p class='muted' style='font-size:12.5px;margin-top:10px'>"
           f"Excedente: <b>{excedente_qtd}</b> interacoes acima do limite &rarr; "
           f"cobrar +{_moeda(excedente_cobr)} (a {_moeda(pl['excedente'])}/interacao).</p>"
           if excedente_qtd else "")
        + "<div style='margin-top:12px;display:flex;gap:8px;align-items:center;flex-wrap:wrap'>"
        "<span class='muted' style='font-size:12px'>Testar o contador:</span>"
        "<form method='post' action='/financeiro/ia/simular' style='display:inline'>"
        "<input type='hidden' name='tipo' value='texto'>"
        "<button class='btn ghost' style='padding:6px 12px;font-size:12.5px'>+ 1 analise (texto)</button></form>"
        "<form method='post' action='/financeiro/ia/simular' style='display:inline'>"
        "<input type='hidden' name='tipo' value='foto'>"
        "<button class='btn ghost' style='padding:6px 12px;font-size:12.5px'>+ 1 leitura (foto)</button></form>"
        "</div>"
        "</div>"
    )

    # ---- custos fixos ----
    custos = financeiro.listar_custos()
    tot_fixos = sum(c["valor"] for c in custos)
    if custos:
        linhas_cx = "".join(
            f"<tr><td>{c['nome']}</td><td>{_moeda(c['valor'])}</td>"
            f"<td style='text-align:right'><form method='post' action='/financeiro/custo/excluir' "
            f"style='display:inline' onsubmit=\"return confirm('Remover este custo?')\">"
            f"<input type='hidden' name='id' value='{c['id']}'>"
            f"<button class='btn ghost' style='padding:3px 10px;font-size:12px'>remover</button>"
            f"</form></td></tr>" for c in custos)
    else:
        linhas_cx = "<tr><td colspan='3' class='muted'>Nenhum custo fixo cadastrado ainda.</td></tr>"
    card_custos = (
        "<div class='card'>"
        "<h3 style='margin-top:0'>&#127974; Custos fixos do mes</h3>"
        "<p class='muted' style='margin-top:-4px'>Aluguel, salarios, embalagem, software, contador&hellip;</p>"
        "<table><tr><th>Descricao</th><th>Valor</th><th></th></tr>"
        f"{linhas_cx}"
        f"<tr><td style='font-weight:600'>Total</td><td style='font-weight:600'>{_moeda(tot_fixos)}</td><td></td></tr>"
        "</table>"
        "<form method='post' action='/financeiro/custo' "
        "style='display:flex;gap:8px;margin-top:14px;flex-wrap:wrap'>"
        "<input name='nome' placeholder='Ex: Aluguel' required "
        "style='flex:1;min-width:160px;padding:9px;border:1px solid #d7dade;border-radius:8px'/>"
        "<input name='valor' placeholder='0,00' required "
        "style='width:120px;padding:9px;border:1px solid #d7dade;border-radius:8px'/>"
        "<button class='btn'>Adicionar</button></form>"
        "</div>"
    )

    # ---- fechamento do mes ----
    cfg = _preco_cfg()
    ini = hoje.replace(day=1).isoformat()
    try:
        _, tt, n_ped = _calc_resultado(ini, hoje.isoformat(), cfg)
        vendas_liq = tt["liq"]
        faturamento = tt["venda"]
    except (RuntimeError, httpx.HTTPStatusError):
        vendas_liq = faturamento = 0.0
        n_ped = 0
    resultado_final = vendas_liq - tot_fixos - custo_brl
    cor_fim = "#0F6E56" if resultado_final >= 0 else "#A32D2D"

    def _linha_fech(rotulo, valor, cor="#1f2430", sinal=""):
        return (f"<div style='display:flex;justify-content:space-between;padding:9px 0;"
                f"border-bottom:1px solid #eef0f2'><span>{rotulo}</span>"
                f"<span style='font-weight:600;color:{cor}'>{sinal}{_moeda(abs(valor))}</span></div>")

    card_fech = (
        "<div class='card'>"
        f"<h3 style='margin-top:0'>&#128202; Fechamento de {_mes_br(res['mes'])}</h3>"
        f"<p class='muted' style='margin-top:-4px'>{n_ped} pedidos no mes &middot; "
        f"faturamento {_moeda(faturamento)}</p>"
        + _linha_fech("Lucro liquido das vendas", vendas_liq, "#0F6E56", "+ ")
        + _linha_fech("Custos fixos", -tot_fixos, "#A32D2D", "&minus; ")
        + _linha_fech("Custo de IA", -custo_brl, "#A32D2D", "&minus; ")
        + "<div style='display:flex;justify-content:space-between;padding:13px 0 2px'>"
        f"<span style='font-weight:700'>Resultado final</span>"
        f"<span style='font-weight:700;font-size:18px;color:{cor_fim}'>{_moeda(resultado_final)}</span></div>"
        "<p class='muted' style='font-size:12px;margin-top:10px'>Lucro das vendas vem da aba "
        "<a href='/resultado'>Resultado</a> (ML, mes atual). O <b>A pagar / A receber do Bling</b> "
        "(notas e boletos) entra aqui quando ativarmos o escopo Financeiro do Bling.</p>"
        "</div>"
    )

    card_bling = (
        "<div class='card' style='background:#FFF7E6;border-color:#FAD89B'>"
        "<h3 style='margin-top:0'>&#129534; Contas a pagar / a receber (Bling) "
        "<span class='pill'>em breve</span></h3>"
        "<p class='muted' style='margin:0'>Vamos puxar notas e boletos direto do Bling para "
        "projetar o caixa e avisar vencimentos. Precisa adicionar o escopo <b>Financeiro</b> no "
        "app do Bling e reconectar &mdash; aviso quando for a hora.</p>"
        "</div>"
    )

    corpo = (
        "<h1>Financeiro</h1>"
        "<p class='muted'>Consumo de IA, custos fixos e o fechamento do mes num lugar so.</p>"
        f"{card_ia}{card_fech}{card_custos}{card_bling}"
    )
    return _pagina(corpo, ativo="financeiro", papel=papel, nome=nome)


@app.post("/financeiro/ia/simular")
def financeiro_ia_simular(request: Request, tipo: str = Form("texto")):
    if _atual(request)[1] != "admin":
        return RedirectResponse("/inbox")
    # modelo padrao por tipo: foto le com Haiku (barato), texto analisa com Sonnet
    modelo = "haiku" if tipo == "foto" else "sonnet"
    ia_consumo.registrar(tipo if tipo in ia_consumo.PERFIS else "texto", modelo=modelo)
    return RedirectResponse("/financeiro", status_code=303)


@app.post("/financeiro/custo")
def financeiro_custo_add(request: Request, nome: str = Form(...), valor: str = Form("0")):
    if _atual(request)[1] != "admin":
        return RedirectResponse("/inbox")
    nome = nome.strip()
    if nome:
        financeiro.adicionar_custo(nome, _num(valor, 0))
    return RedirectResponse("/financeiro", status_code=303)


@app.post("/financeiro/custo/excluir")
def financeiro_custo_del(request: Request, id: int = Form(...)):
    if _atual(request)[1] != "admin":
        return RedirectResponse("/inbox")
    financeiro.remover_custo(id)
    return RedirectResponse("/financeiro", status_code=303)


@app.get("/financeiro/plano", response_class=HTMLResponse)
def financeiro_plano(request: Request):
    nome, papel = _atual(request)
    if papel != "admin":
        return RedirectResponse("/inbox")
    pl = ia_consumo.plano()
    corpo = (
        "<h1>Plano de IA</h1>"
        "<p class='muted'>Quanto voce cobra do cliente pela inteligencia financeira e o limite "
        "incluido. O custo real da API e calculado automaticamente.</p>"
        "<div class='card' style='max-width:520px'>"
        "<form method='post' action='/financeiro/plano' style='display:grid;gap:16px'>"
        "<div><label style='font-size:13px;color:#5b6573'>Interacoes incluidas no pacote (mes)</label>"
        f"<input name='limite' value='{pl['limite']}' "
        "style='width:100%;padding:9px;border:1px solid #d7dade;border-radius:8px'/></div>"
        "<div><label style='font-size:13px;color:#5b6573'>Preco do pacote (R$/mes)</label>"
        f"<input name='preco_pacote' value='{pl['preco_pacote']:g}' "
        "style='width:100%;padding:9px;border:1px solid #d7dade;border-radius:8px'/></div>"
        "<div><label style='font-size:13px;color:#5b6573'>Excedente por interacao (R$)</label>"
        f"<input name='excedente' value='{pl['excedente']:g}' "
        "style='width:100%;padding:9px;border:1px solid #d7dade;border-radius:8px'/>"
        "<div class='muted' style='font-size:11px'>Cobrado por interacao acima do limite.</div></div>"
        "<div><label style='font-size:13px;color:#5b6573'>Cambio US$ &rarr; R$</label>"
        f"<input name='cambio' value='{pl['cambio']:g}' "
        "style='width:100%;padding:9px;border:1px solid #d7dade;border-radius:8px'/>"
        "<div class='muted' style='font-size:11px'>Usado para converter o custo da API (em dolar).</div></div>"
        "<button class='btn'>Salvar</button></form></div>"
        "<p style='margin-top:14px'><a href='/financeiro'>&larr; voltar ao financeiro</a></p>"
    )
    return _pagina(corpo, ativo="financeiro", papel=papel, nome=nome)


@app.post("/financeiro/plano")
def financeiro_plano_salvar(request: Request, limite: str = Form("500"),
                            preco_pacote: str = Form("79"), excedente: str = Form("0.40"),
                            cambio: str = Form("5.50")):
    if _atual(request)[1] != "admin":
        return RedirectResponse("/inbox")
    ia_consumo.salvar_plano(
        limite=int(_num(limite, 500)), preco_pacote=_num(preco_pacote, 79),
        excedente=_num(excedente, 0.40), cambio=_num(cambio, 5.50), markup=3.0)
    return RedirectResponse("/financeiro", status_code=303)


# --------------------------------------------------------------------------- #
# Produtos: lista anuncios do ML e guarda o custo de cada um (alimenta a margem)
# --------------------------------------------------------------------------- #
_STATUS_PROD = {
    "active": ("Ativo", "#0F6E56", "#E5F4EE"),
    "paused": ("Pausado", "#C77700", "#FCF1DD"),
    "closed": ("Encerrado", "#8a93a0", "#EEF0F2"),
    "under_review": ("Em revisao", "#A32D2D", "#FBEAEA"),
}


def _badge_prod(status: str) -> str:
    rot, cor, bg = _STATUS_PROD.get(status, (status or "-", "#5b6573", "#EEF0F2"))
    return f"<span class='badge' style='color:{cor};background:{bg}'>{rot}</span>"


def _val_input(v) -> str:
    return ("%.2f" % v).replace(".", ",") if v is not None else ""


@app.get("/produtos", response_class=HTMLResponse)
def produtos_page(request: Request, conta: str = "", pend: str = ""):
    nome, papel = _atual(request)

    contas = mercadolivre.contas()
    if not contas:
        corpo = ("<h1>Produtos</h1><div class='card'>Nenhuma conta do Mercado Livre "
                 "conectada ainda. <a href='/ml/login'>Conectar conta</a></div>")
        return _pagina(corpo, ativo="produtos", papel=papel, nome=nome)

    custos = produtos.custos()
    fiscais = produtos.fiscal()
    so_pend = pend == "1"

    secoes = ""
    total = com_custo = 0
    erro = False
    for acc in contas:
        uid = str(acc["user_id"])
        if conta and conta != uid:
            continue
        loja = mercadolivre.nome_exibicao(acc)
        try:
            itens = mercadolivre.listar_produtos(user_id=uid, token=acc)
        except (RuntimeError, httpx.HTTPStatusError):
            erro = True
            secoes += (f"<div class='card'><b>{loja}</b><div class='muted'>"
                       "Nao consegui carregar os anuncios desta conta agora.</div></div>")
            continue

        linhas = ""
        n_loja = 0
        for p in itens:
            iid = str(p.get("id") or "")
            custo = custos.get(iid)
            total += 1
            if custo is not None:
                com_custo += 1
            if so_pend and custo is not None:
                continue
            n_loja += 1
            preco = float(p.get("price") or 0)
            sku = p.get("seller_custom_field") or "&mdash;"
            titulo = p.get("title") or iid
            foto = p.get("secure_thumbnail") or p.get("thumbnail") or ""
            link = p.get("permalink") or "#"
            img = (f"<img src='{foto}' style='width:38px;height:38px;border-radius:7px;"
                   "object-fit:cover;background:#eee'/>" if foto else "")
            if custo is not None and preco:
                mb = (preco - custo) / preco * 100
                mb_cor = "#0F6E56" if mb >= 0 else "#A32D2D"
                margem = f"<span style='color:{mb_cor}'>{mb:.0f}%</span>"
            else:
                margem = "<span class='muted'>&mdash;</span>"
            busca = f"{titulo} {p.get('seller_custom_field') or ''}".lower().replace("'", "")
            fi = fiscais.get(iid) or {}

            def _fin(campo, ph, larg):  # input fiscal compacto
                return (f"<input name='{campo}_{iid}' value=\"{_esc(fi.get(campo) or '')}\" "
                        f"placeholder='{ph}' style='width:{larg}px;padding:6px;border:1px "
                        "solid #d7dade;border-radius:6px;font-size:12px'/>")

            linhas += (
                f"<tr data-s=\"{busca}\">"
                f"<td>{img}</td>"
                f"<td><a href='{link}' target='_blank'>{titulo[:60]}</a>"
                f"<div class='muted' style='font-size:11px'>{iid} &middot; SKU {sku}</div></td>"
                f"<td>{_badge_prod(p.get('status'))}</td>"
                f"<td>{_moeda(preco)}</td>"
                f"<td><div style='display:flex;align-items:center;gap:4px'>"
                f"<span class='muted' style='font-size:12px'>R$</span>"
                f"<input name='c_{iid}' value='{_val_input(custo)}' placeholder='0,00' "
                "inputmode='decimal' style='width:90px;padding:7px;border:1px solid #d7dade;"
                "border-radius:7px'/></div></td>"
                f"<td><div style='display:flex;gap:4px'>{_fin('ncm', 'NCM', 78)}"
                f"{_fin('cfop', 'CFOP', 54)}{_fin('cst', 'CST', 54)}</div></td>"
                f"<td style='text-align:right'>{margem}</td></tr>"
            )
        if not linhas:
            linhas = ("<tr><td colspan='7' class='muted'>"
                      + ("Todos os produtos ja tem custo. &#127881;" if so_pend
                         else "Nenhum anuncio nesta conta.") + "</td></tr>")
        secoes += (
            f"<h3 style='margin:22px 0 6px'>{loja} "
            f"<span class='muted' style='font-weight:400;font-size:13px'>"
            f"&middot; {n_loja} anuncio(s)</span></h3>"
            "<table><tr><th></th><th>Produto</th><th>Status</th><th>Preco</th>"
            "<th>Custo (R$)</th><th>Fiscal (NCM &middot; CFOP &middot; CST)</th>"
            "<th style='text-align:right'>Margem bruta</th></tr>"
            f"{linhas}</table>"
        )

    pct = (com_custo / total * 100) if total else 0
    barra_cor = "#0F6E56" if pct >= 80 else ("#C77700" if pct >= 30 else "#A32D2D")
    resumo = (
        "<div class='card'>"
        f"<div style='display:flex;justify-content:space-between;margin-bottom:6px'>"
        f"<b>{com_custo}</b> de {total} produtos com custo preenchido"
        f"<span class='muted'>{pct:.0f}%</span></div>"
        "<div style='background:#e9ebef;border-radius:999px;height:10px;overflow:hidden'>"
        f"<div style='width:{pct:.0f}%;height:100%;background:{barra_cor}'></div></div>"
        "</div>"
    )

    # filtros (conta + so pendentes) + busca
    opts = "<option value=''>Todas as lojas</option>" + "".join(
        f"<option value='{a['user_id']}' {'selected' if conta == str(a['user_id']) else ''}>"
        f"{mercadolivre.nome_exibicao(a)}</option>" for a in contas)
    filtros = (
        "<div style='display:flex;gap:10px;align-items:center;flex-wrap:wrap;margin:6px 0 14px'>"
        "<form method='get' action='/produtos' style='display:flex;gap:8px;align-items:center'>"
        f"<select name='conta' onchange='this.form.submit()' "
        f"style='padding:8px;border:1px solid #d7dade;border-radius:8px'>{opts}</select>"
        f"<label class='muted' style='font-size:13px;display:flex;gap:5px;align-items:center'>"
        f"<input type='checkbox' name='pend' value='1' {'checked' if so_pend else ''} "
        "onchange='this.form.submit()'/> so sem custo</label></form>"
        "<input id='busca' oninput='filtrarProd()' placeholder='Buscar por titulo ou SKU' "
        "style='flex:1;min-width:200px;padding:9px;border:1px solid #d7dade;border-radius:8px'/>"
        "</div>"
    )
    js = ("<script>function filtrarProd(){var q=document.getElementById('busca')"
          ".value.toLowerCase();document.querySelectorAll('tr[data-s]').forEach("
          "function(tr){tr.style.display=tr.getAttribute('data-s').indexOf(q)>=0?'':'none';});}"
          "function aplicarFiscal(){var n=document.getElementById('ap_ncm').value,"
          "f=document.getElementById('ap_cfop').value,s=document.getElementById('ap_cst').value;"
          "document.querySelectorAll('tr[data-s]').forEach(function(tr){"
          "if(tr.style.display=='none')return;"
          "function set(pre,v){if(!v)return;var el=tr.querySelector('input[name^=\"'+pre+'_\"]');"
          "if(el)el.value=v;}set('ncm',n);set('cfop',f);set('cst',s);});}"
          "</script>")

    corpo = (
        "<link rel='stylesheet' href='https://cdn.jsdelivr.net/npm/"
        "@tabler/icons-webfont@3.11.0/dist/tabler-icons.min.css'>"
        "<div style='display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap'>"
        "<h1 style='margin-bottom:4px'>Produtos</h1>"
        "<a class='btn ghost' href='/produtos/planilha'><i class='ti ti-table'></i> "
        "Gerar planilha</a></div>"
        "<p class='muted'>Preencha o <b>custo</b> de cada anuncio (entra na margem em Resultado/Financeiro) "
        "e os <b>dados fiscais</b> (NCM, CFOP, CST/CSOSN) usados na emissao da Nota Fiscal. "
        "Quem nao tiver custo usa o % configurado.</p>"
        "<div class='card' style='display:flex;gap:8px;align-items:center;flex-wrap:wrap'>"
        "<span class='muted' style='font-size:13px'><i class='ti ti-wand'></i> Aplicar fiscal a todos "
        "os visiveis:</span>"
        "<input id='ap_ncm' placeholder='NCM' style='width:90px;padding:6px;border:1px solid #d7dade;border-radius:6px'/>"
        "<input id='ap_cfop' placeholder='CFOP' style='width:70px;padding:6px;border:1px solid #d7dade;border-radius:6px'/>"
        "<input id='ap_cst' placeholder='CST/CSOSN' style='width:90px;padding:6px;border:1px solid #d7dade;border-radius:6px'/>"
        "<button type='button' class='btn ghost' onclick='aplicarFiscal()'>Aplicar</button>"
        "<span class='muted' style='font-size:12px'>Depois clique em <b>Salvar custos</b>.</span></div>"
        "<details class='card'><summary style='cursor:pointer;font-weight:600'>"
        "<i class='ti ti-box'></i> Produtos do balcao (venda fora do ML)</summary>"
        "<p class='muted' style='font-size:13px'>Produtos cadastrados a mao para emitir NF no "
        "balcao. Nao vem do Mercado Livre.</p>"
        + _card_produtos_balcao(balcao.listar_produtos()) + "</details>"
        # filtros ficam FORA do form de salvar (formulario dentro de formulario quebra o envio)
        f"{resumo}{filtros}"
        "<form method='post' action='/produtos/salvar'>"
        "<div style='text-align:right;margin-bottom:8px'><button class='btn'>Salvar custos</button></div>"
        f"{secoes}"
        "<div style='margin-top:18px'><button class='btn'>Salvar custos</button></div>"
        "</form>" + js
    )
    return _pagina(corpo, ativo="produtos", papel=papel, nome=nome)


@app.post("/produtos/salvar")
async def produtos_salvar(request: Request):
    form = await request.form()
    mapa: dict = {}
    fiscal: dict = {}
    for k, v in form.items():
        s = str(v).strip()
        if k.startswith("c_"):
            item_id = k[2:]
            mapa[item_id] = None if s == "" else _num(s, 0)
            continue
        for pre in ("ncm", "cfop", "cst"):
            if k.startswith(pre + "_"):
                item_id = k[len(pre) + 1:]
                fiscal.setdefault(item_id, {})[pre] = s
                break
    if mapa:
        produtos.definir_varios(mapa)
    if fiscal:
        produtos.definir_fiscal_varios(fiscal)
    return RedirectResponse("/produtos", status_code=303)


@app.get("/produtos/planilha")
def produtos_planilha(request: Request):
    """Baixa uma planilha (CSV) de todos os anuncios com preco, custo e margem."""
    custos = produtos.custos()
    buf = io.StringIO()
    buf.write("﻿")  # BOM: Excel abre com acentos certos
    w = csv.writer(buf, delimiter=";")
    w.writerow(["Loja", "Produto", "SKU", "MLB", "Status", "Preco", "Custo",
                "Margem bruta (%)"])

    def _br(v):
        return ("%.2f" % v).replace(".", ",") if v is not None else ""

    for acc in mercadolivre.contas():
        uid = str(acc["user_id"])
        loja = mercadolivre.nome_exibicao(acc)
        try:
            itens = mercadolivre.listar_produtos(user_id=uid, token=acc)
        except (RuntimeError, httpx.HTTPError):
            itens = []
        for p in itens:
            iid = str(p.get("id") or "")
            custo = custos.get(iid)
            preco = float(p.get("price") or 0)
            st = p.get("status") or ""
            rot = _STATUS_PROD.get(st, (st,))[0]
            margem = f"{(preco - custo) / preco * 100:.0f}" if (custo is not None and preco) else ""
            w.writerow([loja, p.get("title") or "", p.get("seller_custom_field") or "",
                        iid, rot, _br(preco), _br(custo), margem])
    fn = f"produtos-{date.today().isoformat()}.csv"
    return Response(buf.getvalue(), media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": f"attachment; filename=\"{fn}\""})


@app.get("/produtos/diag", response_class=HTMLResponse)
def produtos_diag(request: Request):
    """Diagnostico temporario: mostra o que a API do ML responde ao listar itens."""
    nome, papel = _atual(request)
    if papel != "admin":
        return RedirectResponse("/inbox")
    out: list[str] = []
    for acc in mercadolivre.contas():
        uid = str(acc["user_id"])
        out.append(f"=== conta {uid} ({mercadolivre.nome_exibicao(acc)}) ===")
        out.append(f"token scope = {acc.get('scope')!r}")
        ids: list[str] = []
        # 1) busca por offset
        try:
            d = mercadolivre.get(f"/users/{uid}/items/search", {"limit": 5, "offset": 0},
                                 user_id=uid, token=acc)
            total = (d.get("paging") or {}).get("total")
            ids = d.get("results") or []
            out.append(f"[offset] OK  paging.total={total}  results={len(ids)}  amostra={ids[:3]}")
        except httpx.HTTPStatusError as e:
            out.append(f"[offset] ERRO HTTP {e.response.status_code}: {e.response.text[:500]}")
        except Exception as e:
            out.append(f"[offset] EXC {type(e).__name__}: {e}")
        # 2) busca por scan
        try:
            d = mercadolivre.get(f"/users/{uid}/items/search",
                                 {"search_type": "scan", "limit": 5}, user_id=uid, token=acc)
            out.append(f"[scan]   OK  scroll_id={'sim' if d.get('scroll_id') else 'nao'}  "
                       f"results={len(d.get('results') or [])}")
        except httpx.HTTPStatusError as e:
            out.append(f"[scan]   ERRO HTTP {e.response.status_code}: {e.response.text[:500]}")
        except Exception as e:
            out.append(f"[scan]   EXC {type(e).__name__}: {e}")
        # 3) detalhes (multiget) dos primeiros ids achados
        if ids:
            try:
                d = mercadolivre.get("/items", {"ids": ",".join(ids[:3]),
                                                "attributes": "id,title,price,status"},
                                     user_id=uid, token=acc)
                amost = [(x.get("code"), (x.get("body") or {}).get("title"))
                         for x in (d if isinstance(d, list) else [])]
                out.append(f"[detalhes] {amost}")
            except Exception as e:
                out.append(f"[detalhes] EXC {type(e).__name__}: {e}")
        out.append("")
    inner = "\n".join(out).replace("<", "&lt;")
    corpo = ("<h1>Diagnostico de produtos</h1>"
             "<p class='muted'>Pagina temporaria. Me mande o que aparece aqui.</p>"
             f"<pre style='white-space:pre-wrap;font-size:12px;background:#fff;"
             f"border:1px solid #e6e8eb;border-radius:10px;padding:14px'>{inner}</pre>")
    return _pagina(corpo, ativo="produtos", papel=papel, nome=nome)


# --------------------------------------------------------------------------- #
# Pedidos (direto do Mercado Livre, sem depender do Bling) + botao p/ mensagens
# --------------------------------------------------------------------------- #
@app.get("/vendas", response_class=HTMLResponse)
def vendas(request: Request, de: str = "", ate: str = "", loja: str = "",
           q: str = "", pag: int = 1, atualizar: str = "", atend: str = "", fluxo: str = "",
           ordenar: str = "", envio: str = ""):
    nome, papel = _atual(request)
    contas = mercadolivre.contas()
    if not contas:
        corpo = ("<h1>Pedidos</h1><div class='card'>Nenhuma conta do Mercado Livre "
                 "conectada ainda. <a href='/ml/login'>Conectar conta</a></div>")
        return _pagina(corpo, ativo="vendas", papel=papel, nome=nome)

    if atualizar == "1":  # botao "Atualizar agora": ignora o cache e busca do zero
        mercadolivre.invalidar_periodo()

    hoje = date.today()
    de = de or (hoje - timedelta(days=30)).isoformat()
    ate = ate or hoje.isoformat()
    termo = q.strip().lower()

    equipe = [u["nome"] for u in usuarios.listar_usuarios()]
    flx = fluxos.listar_fluxos()
    fm = fluxos.fluxo_marcas()       # pack -> fluxo_id
    am = fluxos.atendente_marcas()   # pack -> atendente

    def _pk(o):
        return str(o.get("pack_id") or o.get("id"))

    # junta os pedidos de todas as contas (ou da loja filtrada)
    registros: list[tuple] = []
    for acc in contas:
        uid = str(acc["user_id"])
        if loja and loja != uid:
            continue
        try:
            pedidos = mercadolivre.pedidos_periodo(de, ate, user_id=uid, token=acc)
        except (RuntimeError, httpx.HTTPError):
            pedidos = []
        try:
            aguardando = mercadolivre.packs_aguardando(uid, acc)
        except (RuntimeError, httpx.HTTPError):
            aguardando = set()
        for o in pedidos:
            registros.append((o, uid, aguardando))

    if termo:
        def _bate(reg):
            o = reg[0]
            cod = str(o.get("id") or "")          # numero do pedido/venda
            pack = str(o.get("pack_id") or "")    # codigo do pacote (o que o cliente manda)
            b = o.get("buyer") or {}
            # apelido + nome real (quando o ML fornece first_name/last_name)
            comp = (f"{b.get('nickname', '')} {b.get('first_name', '')} "
                    f"{b.get('last_name', '')}").lower()
            its = o.get("order_items") or []
            tit = ((its[0].get("item") or {}).get("title") or "").lower() if its else ""
            return termo in cod or termo in pack or termo in comp or termo in tit
        registros = [r for r in registros if _bate(r)]
        # busca por um codigo (pedido OU pacote) que nao esta na lista carregada
        # (ex.: venda fora dos 30 dias): busca direto no ML em qualquer conta.
        q_cod = q.strip()
        if q_cod.isdigit() and not any(
                str(r[0].get("id")) == q_cod or str(r[0].get("pack_id") or "") == q_cod
                for r in registros):
            try:
                o_dir, uid_dir = mercadolivre.buscar_pedido_cod(q_cod, contas)
            except Exception:
                o_dir = None
            if o_dir:
                registros = [(o_dir, str(uid_dir), set())] + registros
    else:
        # filtros de atendente/fluxo so quando NAO ha busca (a busca tem prioridade)
        if atend == "__none__":  # nao direcionados: sem atendente atribuido
            registros = [r for r in registros if not am.get(_pk(r[0]))]
        elif atend:
            registros = [r for r in registros if am.get(_pk(r[0]), "") == atend]
        if fluxo:
            registros = [r for r in registros if str(fm.get(_pk(r[0]), "")) == fluxo]

    # envio (data 'enviar ate' + situacao entregue/enviado/...) - em paralelo com cache
    envio_map: dict = {}   # pk -> {"enviar_ate":..., "status":...}
    acc_by_uid = {str(a["user_id"]): a for a in contas}

    def _fetch_env(reg):
        try:
            return (_pk(reg[0]),
                    mercadolivre.resumo_envio_de(reg[0], user_id=reg[1], token=acc_by_uid.get(reg[1])))
        except Exception:
            return (_pk(reg[0]), {})

    # se precisa ordenar por envio ou filtrar por situacao, busca o envio de um
    # conjunto limitado (mais recentes) para nao ficar lento com milhares
    # (a busca tem prioridade: quando ha termo, nao aplicamos filtro de situacao)
    if (ordenar == "envio" or envio) and not termo:
        with concurrent.futures.ThreadPoolExecutor(max_workers=12) as ex:
            for pk_, res in ex.map(_fetch_env, registros[:150]):
                envio_map[pk_] = res

    if envio and not termo:
        grupo = _ENVIO_GRUPO.get(envio, set())
        registros = [r for r in registros
                     if envio_map.get(_pk(r[0]), {}).get("status", "") in grupo]

    if ordenar == "envio" and not termo:
        registros.sort(key=lambda r: envio_map.get(_pk(r[0]), {}).get("enviar_ate", "") or "9999")
    else:
        registros.sort(key=lambda r: str(r[0].get("date_created") or ""), reverse=True)

    total_n = len(registros)
    por_pag = 25
    pag = max(1, pag)
    ini = (pag - 1) * por_pag
    pagina_itens = registros[ini:ini + por_pag]
    tem_mais = ini + por_pag < total_n

    faltam = [r for r in pagina_itens if _pk(r[0]) not in envio_map]
    if faltam:
        with concurrent.futures.ThreadPoolExecutor(max_workers=10) as ex:
            for pk_, val in ex.map(_fetch_env, faltam):
                envio_map[pk_] = val

    apel = {str(a["user_id"]): mercadolivre.nome_exibicao(a) for a in contas}
    voltar = "/vendas" + ("?" + request.url.query if request.url.query else "")
    voltar = voltar.replace("&atualizar=1", "")  # nao repetir o refresh ao voltar
    voltar_enc = quote(voltar, safe="")  # para levar os filtros ate a conversa e voltar
    selstyle = ("font-size:12px;padding:5px 6px;border:1px solid #d7dade;border-radius:6px;"
                "background:#fff;max-width:160px")

    linhas = ""
    for o, uid, aguardando in pagina_itens:
        pk = _pk(o)
        _b = o.get("buyer") or {}
        _rec = (envio_map.get(pk) or {}).get("nome", "")  # receiver_name (nome do envio)
        _nome_real = f"{_b.get('first_name', '')} {_b.get('last_name', '')}".strip()
        comprador = _rec or _nome_real or _b.get("nickname") or "-"
        comp_id = str(_b.get("id", ""))
        its = o.get("order_items") or []
        titulo = (its[0].get("item") or {}).get("title", "-") if its else "-"
        venda = float(o.get("total_amount") or 0)
        sino = ("<i class='ti ti-bell' style='color:#C77700' "
                "title='Mensagem nao respondida'></i> " if pk in aguardando else "")
        link_msg = f"/conversa?pack={pk}&conta={uid}&buyer={comp_id}&voltar={voltar_enc}"
        pack_disp = (f" &middot; <b>pacote {o.get('pack_id')}</b>"
                     if o.get("pack_id") and str(o.get("pack_id")) != str(o.get("id")) else "")
        res_env = envio_map.get(pk) or {}
        env_ate = res_env.get("enviar_ate", "")
        st_env = res_env.get("status", "")
        env_html = ""
        if env_ate:
            cor_env = "#A32D2D" if env_ate[:10] < hoje.isoformat() else "#A15C00"
            env_html = (f" &middot; <span style='color:{cor_env};font-weight:600'>"
                        f"<i class='ti ti-truck'></i> enviar ate {_data_br(env_ate)}</span>")
        env_badge = _badge_envio(st_env)
        env_badge_html = f"<div style='margin-top:4px'>{env_badge}</div>" if env_badge else ""
        at_atual = am.get(pk, "")
        opt_at = "<option value=''>&mdash; atendente &mdash;</option>" + "".join(
            f"<option value='{_esc(n)}' {'selected' if n == at_atual else ''}>{_esc(n)}</option>"
            for n in equipe)
        fx_atual = fm.get(pk)
        opt_fx = "<option value=''>&mdash; fluxo &mdash;</option>" + "".join(
            f"<option value='{f['id']}' {'selected' if f['id'] == fx_atual else ''}>{_esc(f['nome'])}</option>"
            for f in flx)
        linhas += (
            "<div style='border:1px solid #e6e8eb;border-radius:10px;background:#fff;"
            "margin-bottom:8px;padding:12px 14px'>"
            "<div style='display:flex;justify-content:space-between;gap:14px;align-items:flex-start'>"
            f"<a href='{link_msg}' style='min-width:0;flex:1;color:inherit'>"
            "<div style='font-weight:600;display:flex;align-items:center;gap:6px;flex-wrap:wrap'>"
            f"{sino}{comprador}"
            f"<span class='badge' style='background:#FFF7CC;color:#7a6a00'>{apel.get(uid, uid)}</span></div>"
            "<div class='muted' style='font-size:13px;white-space:nowrap;overflow:hidden;"
            f"text-overflow:ellipsis;max-width:520px;margin-top:1px'>{titulo}</div>"
            "<div class='muted' style='font-size:11px;margin-top:2px'>"
            f"<i class='ti ti-hash' style='font-size:11px'></i> {o.get('id', '-')}{pack_disp}"
            f" &middot; {_data_br(o.get('date_created'))}{env_html}</div></a>"
            "<div style='text-align:right;flex:none'>"
            f"<div style='font-weight:600'>{_moeda(venda)}</div>"
            f"<div style='margin-top:4px'>{_badge_status(o.get('status'))}</div>"
            f"{env_badge_html}</div>"
            "</div>"
            "<div style='display:flex;gap:8px;align-items:center;flex-wrap:wrap;margin-top:10px;"
            "padding-top:10px;border-top:1px solid #f0f1f4'>"
            "<form method='post' action='/vendas/atendente' style='display:inline-flex;"
            "align-items:center;gap:4px;margin:0'>"
            f"<input type='hidden' name='pack' value='{pk}'/>"
            f"<input type='hidden' name='voltar' value='{_esc(voltar)}'/>"
            "<i class='ti ti-user' style='color:#7a828e'></i>"
            f"<select name='atendente' onchange='this.form.submit()' style='{selstyle}'>{opt_at}</select></form>"
            "<form method='post' action='/vendas/fluxo' style='display:inline-flex;"
            "align-items:center;gap:4px;margin:0'>"
            f"<input type='hidden' name='pack' value='{pk}'/>"
            f"<input type='hidden' name='voltar' value='{_esc(voltar)}'/>"
            "<i class='ti ti-git-branch' style='color:#7a828e'></i>"
            f"<select name='fluxo' onchange='this.form.submit()' style='{selstyle}'>{opt_fx}</select></form>"
            f"<a href='{link_msg}' style='margin-left:auto;color:#534AB7;font-size:12.5px;"
            "white-space:nowrap'><i class='ti ti-message'></i> Mensagens &rarr;</a>"
            "</div></div>"
        )
    if not linhas:
        linhas = "<div class='muted' style='padding:14px'>Nenhum pedido no periodo.</div>"

    # filtros (periodo + loja + atendente + fluxo + busca)
    campo = "padding:9px;border:1px solid #d7dade;border-radius:8px"
    opt_loja = "<option value=''>Todas as lojas</option>" + "".join(
        f"<option value='{a['user_id']}' {'selected' if loja == str(a['user_id']) else ''}>"
        f"{mercadolivre.nome_exibicao(a)}</option>" for a in contas)
    opt_at_f = ("<option value=''>Todos atendentes</option>"
                f"<option value='__none__' {'selected' if atend == '__none__' else ''}>"
                "Aberto (sem atendente)</option>"
                + "".join(
                    f"<option value='{_esc(n)}' {'selected' if atend == n else ''}>{_esc(n)}</option>"
                    for n in equipe))
    opt_fx_f = "<option value=''>Todos fluxos</option>" + "".join(
        f"<option value='{f['id']}' {'selected' if fluxo == str(f['id']) else ''}>{_esc(f['nome'])}</option>"
        for f in flx)
    opt_env_f = "<option value=''>Toda situacao</option>" + "".join(
        f"<option value='{v}' {'selected' if envio == v else ''}>{lbl}</option>"
        for v, lbl in [("a_enviar", "A enviar"), ("enviado", "Enviado"),
                       ("entregue", "Entregue"), ("nao_entregue", "Nao entregue")])
    filtros = (
        "<form method='get' action='/vendas' "
        "style='display:flex;gap:8px;align-items:flex-end;flex-wrap:wrap;margin:6px 0 14px'>"
        f"<div><div class='muted' style='font-size:12px'>De</div>"
        f"<input type='date' name='de' value='{de}' style='{campo}'/></div>"
        f"<div><div class='muted' style='font-size:12px'>Ate</div>"
        f"<input type='date' name='ate' value='{ate}' style='{campo}'/></div>"
        f"<div><div class='muted' style='font-size:12px'>Loja</div>"
        f"<select name='loja' style='{campo}'>{opt_loja}</select></div>"
        f"<div><div class='muted' style='font-size:12px'>Atendente</div>"
        f"<select name='atend' onchange='this.form.submit()' style='{campo}'>{opt_at_f}</select></div>"
        f"<div><div class='muted' style='font-size:12px'>Fluxo</div>"
        f"<select name='fluxo' onchange='this.form.submit()' style='{campo}'>{opt_fx_f}</select></div>"
        f"<div><div class='muted' style='font-size:12px'>Situacao</div>"
        f"<select name='envio' style='{campo}'>{opt_env_f}</select></div>"
        f"<div><div class='muted' style='font-size:12px'>Ordenar</div>"
        f"<select name='ordenar' style='{campo}'><option value=''>Recentes</option>"
        f"<option value='envio' {'selected' if ordenar == 'envio' else ''}>Enviar ate (prazo)</option>"
        "</select></div>"
        "<div style='flex:1;min-width:140px'><div class='muted' style='font-size:12px'>Busca</div>"
        f"<input name='q' value='{q}' placeholder='nº da venda, nome do cliente ou produto' style='width:100%;{campo}'/></div>"
        "<button class='btn'>Filtrar</button></form>"
    )

    # paginacao (some quando esta buscando)
    nav = ""
    if not termo:
        base = (f"/vendas?de={de}&ate={ate}&loja={loja}&atend={atend}&fluxo={fluxo}"
                f"&ordenar={ordenar}&envio={envio}")
        partes = []
        if pag > 1:
            partes.append(f"<a class='btn ghost' href='{base}&pag={pag - 1}'>&larr; Recentes</a>")
        partes.append(f"<span class='muted' style='font-size:12px'>Pagina {pag}</span>")
        if tem_mais:
            partes.append(f"<a class='btn ghost' href='{base}&pag={pag + 1}'>Mais antigos &rarr;</a>")
        nav = ("<div style='display:flex;gap:8px;align-items:center;justify-content:center;"
               "margin-top:14px'>" + "".join(partes) + "</div>")

    ger_fluxos = ("<a class='muted' href='/fluxos' style='font-size:13px'>"
                  "<i class='ti ti-settings'></i> gerenciar fluxos</a>" if papel == "admin" else "")
    atualizar_href = (f"/vendas?de={de}&ate={ate}&loja={loja}&atend={atend}&fluxo={fluxo}"
                      f"&ordenar={ordenar}&envio={envio}&q={q}&atualizar=1")
    corpo = (
        "<link rel='stylesheet' href='https://cdn.jsdelivr.net/npm/"
        "@tabler/icons-webfont@3.11.0/dist/tabler-icons.min.css'>"
        "<div style='display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap'>"
        "<h1 style='margin-bottom:4px'>Pedidos</h1>"
        f"{ger_fluxos}</div>"
        "<p class='muted'>Direto do Mercado Livre. Clique no pedido para abrir as mensagens; "
        "defina o <b>atendente</b> e o <b>fluxo</b> de cada pedido.</p>"
        f"{filtros}"
        "<div style='display:flex;justify-content:space-between;align-items:center;"
        "flex-wrap:wrap;gap:8px;margin-bottom:8px'>"
        f"<span class='muted' style='font-size:13px'>{total_n} pedido(s) no periodo "
        f"{_data_br(de)} a {_data_br(ate)}.</span>"
        f"<a class='btn ghost' href='{atualizar_href}' "
        "style='padding:6px 12px;font-size:12.5px' title='Buscar pedidos novos agora'>"
        "<i class='ti ti-refresh'></i> Atualizar agora</a></div>"
        f"<div>{linhas}</div>{nav}"
    )
    return _pagina(corpo, ativo="vendas", papel=papel, nome=nome)


@app.post("/vendas/atendente")
def vendas_atendente(request: Request, pack: str = Form(...), atendente: str = Form(""),
                     voltar: str = Form("/vendas")):
    fluxos.definir_atendente(pack, atendente.strip())
    return RedirectResponse(voltar or "/vendas", status_code=303)


@app.post("/vendas/fluxo")
def vendas_fluxo(request: Request, pack: str = Form(...), fluxo: str = Form(""),
                 voltar: str = Form("/vendas")):
    fid = int(fluxo) if fluxo.strip().isdigit() else None
    fluxos.marcar_fluxo(pack, fid)
    return RedirectResponse(voltar or "/vendas", status_code=303)


@app.get("/fluxos", response_class=HTMLResponse)
def fluxos_page(request: Request):
    nome, papel = _atual(request)
    if papel != "admin":
        return RedirectResponse("/inbox")
    lista = fluxos.listar_fluxos()
    linhas = ""
    for f in lista:
        linhas += (
            "<tr><td>"
            "<form method='post' action='/fluxos/renomear' style='display:flex;gap:6px;margin:0'>"
            f"<input type='hidden' name='id' value='{f['id']}'/>"
            f"<input name='nome' value='{_esc(f['nome'])}' "
            "style='flex:1;padding:7px;border:1px solid #d7dade;border-radius:7px'/>"
            "<button class='btn ghost' style='padding:4px 10px;font-size:12px'>salvar</button></form>"
            "</td><td style='text-align:right;width:90px'>"
            "<form method='post' action='/fluxos/excluir' style='display:inline' "
            "onsubmit=\"return confirm('Excluir este fluxo?')\">"
            f"<input type='hidden' name='id' value='{f['id']}'/>"
            "<button class='btn ghost' style='padding:4px 10px;font-size:12px'>excluir</button></form>"
            "</td></tr>"
        )
    if not lista:
        linhas = "<tr><td colspan='2' class='muted'>Nenhum fluxo cadastrado ainda.</td></tr>"
    corpo = (
        "<h1>Fluxos de atendimento</h1>"
        "<p class='muted'>Crie as etapas do seu atendimento (ex.: <i>Aguardando arte, "
        "Em producao, Enviado</i>). Depois voce marca o fluxo de cada pedido na aba Pedidos.</p>"
        "<div class='card' style='max-width:520px'>"
        f"<table><tr><th>Fluxo</th><th></th></tr>{linhas}</table>"
        "<form method='post' action='/fluxos/criar' style='display:flex;gap:8px;margin-top:14px'>"
        "<input name='nome' placeholder='Novo fluxo (ex: Aguardando arte)' required "
        "style='flex:1;padding:9px;border:1px solid #d7dade;border-radius:8px'/>"
        "<button class='btn'>Adicionar</button></form></div>"
        "<p style='margin-top:14px'><a href='/vendas'>&larr; voltar aos pedidos</a></p>"
    )
    return _pagina(corpo, ativo="vendas", papel=papel, nome=nome)


@app.post("/fluxos/criar")
def fluxos_criar(request: Request, nome: str = Form(...)):
    if _atual(request)[1] != "admin":
        return RedirectResponse("/inbox")
    if nome.strip():
        fluxos.criar_fluxo(nome.strip())
    return RedirectResponse("/fluxos", status_code=303)


@app.post("/fluxos/renomear")
def fluxos_renomear(request: Request, id: int = Form(...), nome: str = Form(...)):
    if _atual(request)[1] != "admin":
        return RedirectResponse("/inbox")
    if nome.strip():
        fluxos.renomear_fluxo(id, nome.strip())
    return RedirectResponse("/fluxos", status_code=303)


@app.post("/fluxos/excluir")
def fluxos_excluir(request: Request, id: int = Form(...)):
    if _atual(request)[1] != "admin":
        return RedirectResponse("/inbox")
    fluxos.excluir_fluxo(id)
    return RedirectResponse("/fluxos", status_code=303)


@app.get("/conversa", response_class=HTMLResponse)
def conversa(request: Request, pack: str = "", conta: str = "", buyer: str = "",
             voltar: str = ""):
    """Conversa focada de UM pedido (rapida): abre direto do pedido, sem carregar
    a caixa de entrada inteira. Aceita codigo de pedido ou de pacote."""
    nome, papel = _atual(request)
    contas = mercadolivre.contas()
    if not contas:
        return RedirectResponse("/ml/login")
    acc = next((a for a in contas if str(a["user_id"]) == conta), None) or contas[0]
    uid = str(acc["user_id"])
    try:
        o = mercadolivre.obter_pedido(pack, token=acc) or mercadolivre.pedido_do_pack(pack, token=acc) or {}
    except (RuntimeError, httpx.HTTPError):
        o = {}
    try:
        mensagens = mercadolivre.listar_mensagens(pack, user_id=uid, token=acc)
    except (RuntimeError, httpx.HTTPError):
        mensagens = []
    try:
        env = mercadolivre.dados_envio(o, user_id=uid, token=acc) if o else {}
    except Exception:
        env = {}

    comprador = (o.get("buyer") or {}).get("nickname") or "Comprador"
    comp_id = buyer or str((o.get("buyer") or {}).get("id") or "")
    loja = mercadolivre.nome_exibicao(acc)
    pack_id = str(o.get("pack_id") or "")
    oid = str(o.get("id") or "")
    ship_id = str((o.get("shipping") or {}).get("id") or "")

    # pacote com varios pedidos do mesmo comprador -> mostra todos os itens juntos
    pedidos_pack = [o]
    if pack_id and pack_id != oid:
        try:
            pp = mercadolivre.orders_do_pack(pack_id, user_id=uid, token=acc)
            if pp:
                pedidos_pack = pp
        except (RuntimeError, httpx.HTTPError):
            pass
    titulos = [(it.get("item") or {}).get("title") for ped in pedidos_pack
               for it in (ped.get("order_items") or []) if (it.get("item") or {}).get("title")]
    titulo = " + ".join(titulos) if titulos else "-"
    total = sum(float(ped.get("total_amount") or 0) for ped in pedidos_pack)

    baloes = ""
    for m in mensagens:
        eu = str((m.get("from") or {}).get("user_id", "")) == uid
        txt = (m.get("text") or "").replace("<", "&lt;")
        baloes += f"<div class='bub {'me' if eu else 'them'}'>{txt}{_anexos_html(m, uid)}</div>"
    if not baloes:
        baloes = "<p class='muted' style='text-align:center'>Sem mensagens nesta conversa ainda.</p>"

    cod_html = f"# {oid}"
    if pack_id and pack_id != oid:
        cod_html += f" &middot; pacote {pack_id}"

    try:
        nota_ml = mercadolivre.nota_ml(o, user_id=uid, token=acc) if o else None
    except Exception:
        nota_ml = None
    nf_html = _nf_ordbar(pack, uid, voltar, papel, nota_ml)

    corpo = (
        "<link rel='stylesheet' href='https://cdn.jsdelivr.net/npm/"
        "@tabler/icons-webfont@3.11.0/dist/tabler-icons.min.css'>"
        f"<p><a href='{_esc(voltar) if voltar else '/vendas'}'>&larr; voltar aos pedidos</a></p>"
        "<div class='card' style='padding:0;overflow:hidden;max-width:760px'>"
        "<div class='dhead'>"
        f"<div class='av' style='background:#FFF7CC;color:#7a6a00'>{comprador[:2].upper()}</div>"
        f"<div style='flex:1'><div style='font-weight:600'>{comprador}</div>"
        f"<div class='muted' style='font-size:12px'>Mercado Livre &middot; {loja}</div></div>"
        f"{_badge_status(o.get('status'))}</div>"
        f"<div class='ordbar'><span><i class='ti ti-package'></i> {_esc(titulo[:90])}"
        + (f" <b>({len(pedidos_pack)} pedidos no pacote)</b>" if len(pedidos_pack) > 1 else "")
        + "</span>"
        f"<span><i class='ti ti-cash'></i> {_moeda(total)}</span>"
        + (f"<span style='color:#A15C00;font-weight:500'><i class='ti ti-truck'></i> "
           f"Enviar ate {_data_br(env.get('enviar_ate'))}</span>" if env.get("enviar_ate") else "")
        + (f"<span>{_badge_envio(env.get('envio_status'))}</span>" if env.get("envio_status") else "")
        + f"<span><i class='ti ti-hash'></i> {cod_html}</span>"
        f"<a href='/imprimir?pack={pack}&conta={uid}' target='_blank' "
        "style='color:#534AB7;font-weight:500'><i class='ti ti-printer'></i> Imprimir pedido</a>"
        + (f"<a href='/nf/ml/etiqueta?pack={pack}&conta={uid}' target='_blank' "
           "style='color:#0F6E56;font-weight:600'><i class='ti ti-tag'></i> Etiqueta + DANFE</a>"
           if ship_id else "")
        + f"{nf_html}</div>"
        f"<div class='thread' style='height:auto;max-height:60vh' id='thread'>{baloes}</div>"
        "<form class='reply' method='post' action='/conversa/responder'>"
        f"<input type='hidden' name='pack' value='{pack}'/>"
        f"<input type='hidden' name='conta' value='{uid}'/>"
        f"<input type='hidden' name='buyer' value='{comp_id}'/>"
        f"<input type='hidden' name='voltar' value='{_esc(voltar)}'/>"
        "<input name='texto' placeholder='Responder o comprador...' required/>"
        "<button class='btn ml' type='submit'>Enviar</button></form>"
        "</div>"
        "<script>var t=document.getElementById('thread');if(t)t.scrollTop=t.scrollHeight;</script>"
    )
    return _pagina(corpo, ativo="vendas", papel=papel, nome=nome)


@app.post("/conversa/responder")
def conversa_responder(request: Request, pack: str = Form(...), conta: str = Form(""),
                       buyer: str = Form(""), texto: str = Form(...), voltar: str = Form("")):
    try:
        mercadolivre.enviar_mensagem(pack, buyer, texto, user_id=conta or None)
        nome, _ = _atual(request)
        usuarios.registrar(nome or "?", "conversa_responder", pack)
    except (RuntimeError, httpx.HTTPStatusError):
        pass
    v = f"&voltar={quote(voltar, safe='')}" if voltar else ""
    return RedirectResponse(f"/conversa?pack={pack}&conta={conta}&buyer={buyer}{v}",
                            status_code=303)


# --------------------------------------------------------------------------- #
# Nota Fiscal (NF-e) via provedor fiscal (Focus NFe) -- ver app/nfe.py
# --------------------------------------------------------------------------- #
_NF_BADGE = {
    # status do Focus (pt) e do Mercado Livre (en)
    "autorizado": ("Autorizada", "#0F6E56", "#E4F3EE"),
    "authorized": ("Autorizada", "#0F6E56", "#E4F3EE"),
    "processando_autorizacao": ("Processando", "#7A5B00", "#FBF3D6"),
    "processando": ("Processando", "#7A5B00", "#FBF3D6"),
    "pending": ("Processando", "#7A5B00", "#FBF3D6"),
    "processing": ("Processando", "#7A5B00", "#FBF3D6"),
    "erro_autorizacao": ("Erro na SEFAZ", "#A32D2D", "#F8E5E5"),
    "erro": ("Erro", "#A32D2D", "#F8E5E5"),
    "error": ("Erro", "#A32D2D", "#F8E5E5"),
    "denegado": ("Denegada", "#A32D2D", "#F8E5E5"),
    "cancelado": ("Cancelada", "#555", "#eee"),
    "cancelled": ("Cancelada", "#555", "#eee"),
    "canceled": ("Cancelada", "#555", "#eee"),
}


def _badge_nf(status: str) -> str:
    rot, cor, bg = _NF_BADGE.get(status or "", (status or "-", "#555", "#eee"))
    return (f"<span style='background:{bg};color:{cor};padding:2px 8px;border-radius:999px;"
            f"font-size:12px;font-weight:600'>NF {rot}</span>")


def _nf_ordbar(pack: str, uid: str, voltar: str, papel: str,
               nota_ml: dict | None = None) -> str:
    """Trecho da barra do pedido com o status da NF ou o botao de emitir.

    Prioridade: (1) NF emitida pelo proprio Mercado Livre (puxa DANFE/XML);
    (2) NF emitida pelo Focus (nosso), com botao de emitir se ainda nao houver."""
    v = f"&voltar={quote(voltar, safe='')}" if voltar else ""
    # (1) Nota do proprio Mercado Livre
    if nota_ml:
        partes = [_badge_nf(nota_ml.get("status"))]
        num = str(nota_ml.get("numero") or "")
        serie = str(nota_ml.get("serie") or "")
        if num:
            partes.append(f"<span class='muted'>NF {num}" + (f"/{serie}" if serie else "")
                          + " &middot; ML</span>")
        if nota_ml.get("danfe_path"):
            partes.append(f"<a href='/nf/ml/danfe?pack={pack}&conta={uid}' target='_blank' "
                          "style='color:#534AB7;font-weight:500'>"
                          "<i class='ti ti-file-invoice'></i> DANFE</a>")
        if nota_ml.get("xml_path"):
            partes.append(f"<a href='/nf/ml/xml?pack={pack}&conta={uid}' target='_blank' "
                          "class='muted'>XML</a>")
        return ("<span style='display:flex;gap:10px;align-items:center;flex-wrap:wrap'>"
                + " ".join(partes) + "</span>")
    # (2) Nota emitida pelo nosso provedor (Focus)
    try:
        nota = nfe.por_pack(pack)
    except Exception:
        nota = None
    if nota:
        partes = [_badge_nf(nota.get("status"))]
        if nota.get("numero"):
            partes.append(f"<span class='muted'>n {nota['numero']}</span>")
        if nota.get("danfe_url"):
            partes.append(f"<a href='{_esc(nota['danfe_url'])}' target='_blank' "
                          "style='color:#534AB7;font-weight:500'>"
                          "<i class='ti ti-file-invoice'></i> DANFE</a>")
        if nota.get("xml_url"):
            partes.append(f"<a href='{_esc(nota['xml_url'])}' target='_blank' class='muted'>XML</a>")
        partes.append(f"<a href='/nf/status?ref={quote(nota.get('ref', ''), safe='')}&pack={pack}"
                      f"&conta={uid}{v}' class='muted'><i class='ti ti-refresh'></i> atualizar</a>")
        msg = ""
        if nota.get("status") in ("erro_autorizacao", "erro", "denegado") and nota.get("mensagem"):
            msg = ("<div class='muted' style='font-size:11px;color:#A32D2D;width:100%'>"
                   f"{_esc(str(nota['mensagem'])[:180])}</div>")
        return ("<span style='display:flex;gap:10px;align-items:center;flex-wrap:wrap'>"
                + " ".join(partes) + "</span>" + msg)
    if papel != "admin":
        return ""
    if not nfe.configurado():
        return ("<span class='muted' style='font-size:12px'>"
                "<i class='ti ti-file-invoice'></i> NF: configurar Focus NFe</span>")
    return (f"<form method='post' action='/nf/emitir' style='display:inline'>"
            f"<input type='hidden' name='pack' value='{pack}'/>"
            f"<input type='hidden' name='conta' value='{uid}'/>"
            f"<input type='hidden' name='voltar' value='{_esc(voltar)}'/>"
            "<button class='btn ghost' style='padding:4px 10px;font-size:13px' "
            "onclick=\"return confirm('Emitir a Nota Fiscal deste pedido?')\">"
            "<i class='ti ti-file-invoice'></i> Emitir NF</button></form>")


def _nfe_payload(o: dict, env: dict, fat: dict) -> dict:
    """Monta o corpo da NF-e (formato Focus NFe) a partir do pedido do ML."""
    fisc_map = produtos.fiscal()
    itens = []
    for i, it in enumerate(o.get("order_items") or [], start=1):
        item = it.get("item") or {}
        iid = str(item.get("id") or "")
        fi = fisc_map.get(iid) or {}
        qtd = float(it.get("quantity") or 1)
        unit = round(float(it.get("unit_price") or 0), 2)
        und = (fi.get("unidade") or "UN")[:6]
        itens.append({
            "numero_item": i,
            "codigo_produto": iid or f"ITEM{i}",
            "descricao": (item.get("title") or "Item")[:120],
            "cfop": fi.get("cfop") or "5102",
            "unidade_comercial": und,
            "quantidade_comercial": qtd,
            "valor_unitario_comercial": unit,
            "valor_bruto": round(unit * qtd, 2),
            "unidade_tributavel": und,
            "quantidade_tributavel": qtd,
            "valor_unitario_tributavel": unit,
            "ncm": (fi.get("ncm") or "").replace(".", "") or "49111090",
            "icms_origem": int(fi.get("origem") or 0),
            "icms_situacao_tributaria": fi.get("cst") or "102",
        })
    pay = {
        "natureza_operacao": "Venda de mercadoria",
        "tipo_documento": 1,
        "finalidade_emissao": 1,
        "consumidor_final": 1,
        "presenca_comprador": 2,  # operacao nao presencial (internet)
        "modalidade_frete": 9,
        "nome_destinatario": (fat.get("nome") or env.get("nome") or "Consumidor final")[:60],
        "logradouro_destinatario": env.get("rua") or "",
        "numero_destinatario": env.get("numero") or "S/N",
        "complemento_destinatario": (env.get("complemento") or "")[:60],
        "bairro_destinatario": env.get("bairro") or "",
        "municipio_destinatario": env.get("cidade") or "",
        "uf_destinatario": env.get("estado") or "",
        "cep_destinatario": (env.get("cep") or "").replace("-", ""),
        "pais_destinatario": "Brasil",
        "indicador_inscricao_estadual_destinatario": 9,  # 9 = nao contribuinte
        "items": itens,
    }
    doc = fat.get("doc_numero") or ""
    if fat.get("doc_tipo") == "CNPJ" and doc:
        pay["cnpj_destinatario"] = doc
    elif doc:
        pay["cpf_destinatario"] = doc
    if nfe.CNPJ_EMITENTE:
        pay["cnpj_emitente"] = nfe.CNPJ_EMITENTE
    return pay


@app.post("/nf/emitir")
def nf_emitir(request: Request, pack: str = Form(...), conta: str = Form(""),
              voltar: str = Form("")):
    nome, papel = _atual(request)
    if papel != "admin":
        return RedirectResponse("/inbox")
    contas = mercadolivre.contas()
    acc = next((a for a in contas if str(a["user_id"]) == conta), None) or (contas[0] if contas else None)
    uid = str(acc["user_id"]) if acc else conta
    try:
        o = (mercadolivre.obter_pedido(pack, token=acc)
             or mercadolivre.pedido_do_pack(pack, token=acc) or {})
        env = mercadolivre.dados_envio(o, user_id=uid, token=acc) if o else {}
        fat = (mercadolivre.dados_faturamento(str(o.get("id") or pack), user_id=uid, token=acc)
               if o else {})
        nfe.emitir(pack, uid, _nfe_payload(o, env, fat))
        usuarios.registrar(nome or "?", "nf_emitir", pack)
    except Exception:
        pass
    v = f"&voltar={quote(voltar, safe='')}" if voltar else ""
    return RedirectResponse(f"/conversa?pack={pack}&conta={uid}{v}", status_code=303)


@app.get("/nf/status")
def nf_status(request: Request, ref: str = "", pack: str = "", conta: str = "",
              voltar: str = ""):
    if _atual(request)[1] != "admin":
        return RedirectResponse("/inbox")
    try:
        nfe.atualizar(ref)
    except Exception:
        pass
    if voltar.startswith("/"):  # ex.: balcao manda voltar=/balcao
        return RedirectResponse(voltar, status_code=303)
    v = f"&voltar={quote(voltar, safe='')}" if voltar else ""
    return RedirectResponse(f"/conversa?pack={pack}&conta={conta}{v}", status_code=303)


def _baixar_nota_ml(pack: str, conta: str, tipo: str):
    """Baixa a DANFE (tipo='danfe') ou o XML (tipo='xml') da NF emitida pelo ML."""
    contas = mercadolivre.contas()
    if not contas:
        return RedirectResponse("/ml/login")
    acc = next((a for a in contas if str(a["user_id"]) == conta), None) or contas[0]
    uid = str(acc["user_id"])
    try:
        o = (mercadolivre.obter_pedido(pack, token=acc)
             or mercadolivre.pedido_do_pack(pack, token=acc) or {})
        nota = mercadolivre.nota_ml(o, user_id=uid, token=acc) if o else None
    except Exception:
        nota = None
    if not nota:
        return Response("Nota fiscal do Mercado Livre nao encontrada para este pedido.",
                        status_code=404, media_type="text/plain; charset=utf-8")
    path = nota.get("danfe_path") if tipo == "danfe" else nota.get("xml_path")
    if not path:
        return Response("Arquivo indisponivel.", status_code=404,
                        media_type="text/plain; charset=utf-8")
    try:
        conteudo, ctype = mercadolivre.baixar(path, user_id=uid, token=acc)
    except Exception:
        return Response("Nao consegui baixar a nota do Mercado Livre agora.",
                        status_code=502, media_type="text/plain; charset=utf-8")
    num = str(nota.get("numero") or pack)
    if tipo == "danfe":
        ctype = ctype if "pdf" in ctype else "application/pdf"
        disp = f"inline; filename=\"danfe-{num}.pdf\""
    else:
        ctype = ctype if "xml" in ctype else "application/xml"
        disp = f"attachment; filename=\"nfe-{num}.xml\""
    return Response(conteudo, media_type=ctype, headers={"Content-Disposition": disp})


@app.get("/nf/ml/danfe")
def nf_ml_danfe(request: Request, pack: str = "", conta: str = ""):
    return _baixar_nota_ml(pack, conta, "danfe")


@app.get("/nf/ml/xml")
def nf_ml_xml(request: Request, pack: str = "", conta: str = ""):
    return _baixar_nota_ml(pack, conta, "xml")


@app.get("/nf/ml/etiqueta")
def nf_ml_etiqueta(request: Request, pack: str = "", conta: str = ""):
    """Etiqueta de envio do ML (com a DANFE simplificada junto, se o vendedor
    tiver ativado a impressao conjunta nas preferencias de venda do ML)."""
    contas = mercadolivre.contas()
    if not contas:
        return RedirectResponse("/ml/login")
    acc = next((a for a in contas if str(a["user_id"]) == conta), None) or contas[0]
    uid = str(acc["user_id"])
    try:
        o = (mercadolivre.obter_pedido(pack, token=acc)
             or mercadolivre.pedido_do_pack(pack, token=acc) or {})
    except Exception:
        o = {}
    ship = str((o.get("shipping") or {}).get("id") or "")
    if not ship:
        return Response("Pedido sem envio (shipment) para gerar a etiqueta.",
                        status_code=404, media_type="text/plain; charset=utf-8")
    try:
        conteudo, ctype = mercadolivre.baixar(
            f"/shipment_labels?shipment_ids={ship}&response_type=pdf", user_id=uid, token=acc)
    except Exception:
        return Response("Nao consegui gerar a etiqueta agora. O ML costuma liberar a etiqueta "
                        "quando o envio esta pronto para despacho.", status_code=502,
                        media_type="text/plain; charset=utf-8")
    ctype = ctype if "pdf" in ctype else "application/pdf"
    return Response(conteudo, media_type=ctype,
                    headers={"Content-Disposition": f"inline; filename=\"etiqueta-{ship}.pdf\""})


@app.get("/nf/ml/diag", response_class=HTMLResponse)
def nf_ml_diag(request: Request, cod: str = ""):
    """Diagnostico da NF do Mercado Livre: dado um codigo de pedido/pacote,
    consulta a API de invoices do ML e mostra a resposta crua (status + json)."""
    nome, papel = _atual(request)
    if papel != "admin":
        return RedirectResponse("/inbox")
    contas = mercadolivre.contas()
    out: list[str] = []
    codigos = [c.strip() for c in cod.replace(",", " ").split() if c.strip()]
    if not codigos:
        out.append("Informe um codigo de pedido ou pacote em ?cod=NUMERO")
    for code in codigos:
        out.append(f"===== codigo {code} =====")
        achou = False
        for acc in contas:
            uid = str(acc["user_id"])
            loja = mercadolivre.nome_exibicao(acc)
            try:
                o = (mercadolivre.obter_pedido(code, token=acc)
                     or mercadolivre.pedido_do_pack(code, token=acc))
            except Exception as e:
                out.append(f"  [{loja}] erro ao achar pedido: {type(e).__name__}")
                continue
            if not o:
                continue
            achou = True
            oid = str(o.get("id") or "")
            sid = str((o.get("seller") or {}).get("id") or uid)
            ship = str((o.get("shipping") or {}).get("id") or "")
            out.append(f"  [{loja}] pedido {oid} | seller {sid} | status={o.get('status')} "
                       f"| pago={o.get('status') == 'paid'} | shipment={ship or '-'}")
            st, body = mercadolivre.get_status(f"/users/{sid}/invoices/orders/{oid}",
                                               user_id=uid, token=acc)
            out.append(f"    GET /users/{sid}/invoices/orders/{oid} -> HTTP {st}")
            out.append("    " + json.dumps(body, ensure_ascii=False, indent=2)[:2500])
            if ship:
                st2, body2 = mercadolivre.get_status(
                    f"/users/{sid}/invoices/shipments/{ship}", user_id=uid, token=acc)
                out.append(f"    GET /users/{sid}/invoices/shipments/{ship} -> HTTP {st2}")
                out.append("    " + json.dumps(body2, ensure_ascii=False, indent=2)[:1500])
            break
        if not achou:
            out.append("  pedido nao encontrado em nenhuma conta conectada.")

    corpo = ("<h1>Diagnostico NF do Mercado Livre</h1>"
             "<form method='get' style='margin-bottom:12px'>"
             "<input name='cod' placeholder='numero do pedido ou pacote' "
             f"value='{_esc(cod)}' style='padding:8px;border:1px solid #d7dade;"
             "border-radius:8px;min-width:280px'/> "
             "<button class='btn'>Consultar</button></form>"
             "<pre style='background:#0d1117;color:#c9d1d9;padding:14px;border-radius:10px;"
             "overflow:auto;font-size:12px;line-height:1.5'>"
             + _esc("\n".join(out)) + "</pre>")
    return _pagina(corpo, papel=papel, nome=nome)


# --------------------------------------------------------------------------- #
# Balcao: cadastro de clientes/produtos + emissao de NF avulsa (Focus)
# --------------------------------------------------------------------------- #
def _nfe_payload_balcao(cli: dict, linhas: list) -> dict:
    """Monta a NF-e (formato Focus) de uma venda no balcao (cliente + itens)."""
    itens = []
    for i, (p, qtd) in enumerate(linhas, start=1):
        unit = round(float(p.get("preco") or 0), 2)
        und = (p.get("unidade") or "UN")[:6]
        itens.append({
            "numero_item": i,
            "codigo_produto": f"BAL{p.get('id')}",
            "descricao": (p.get("nome") or "Item")[:120],
            "cfop": p.get("cfop") or "5102",
            "unidade_comercial": und,
            "quantidade_comercial": qtd,
            "valor_unitario_comercial": unit,
            "valor_bruto": round(unit * qtd, 2),
            "unidade_tributavel": und,
            "quantidade_tributavel": qtd,
            "valor_unitario_tributavel": unit,
            "ncm": (p.get("ncm") or "").replace(".", "") or "49111090",
            "icms_origem": int(p.get("origem") or 0),
            "icms_situacao_tributaria": p.get("cst") or "102",
        })
    pay = {
        "natureza_operacao": "Venda de mercadoria",
        "tipo_documento": 1,
        "finalidade_emissao": 1,
        "consumidor_final": 1,
        "presenca_comprador": 1,  # operacao presencial (balcao)
        "modalidade_frete": 9,
        "nome_destinatario": (cli.get("nome") or "Consumidor final")[:60],
        "logradouro_destinatario": cli.get("rua") or "",
        "numero_destinatario": cli.get("numero") or "S/N",
        "complemento_destinatario": (cli.get("complemento") or "")[:60],
        "bairro_destinatario": cli.get("bairro") or "",
        "municipio_destinatario": cli.get("cidade") or "",
        "uf_destinatario": cli.get("uf") or "",
        "cep_destinatario": (cli.get("cep") or "").replace("-", ""),
        "pais_destinatario": "Brasil",
        "indicador_inscricao_estadual_destinatario": 1 if cli.get("ie") else 9,
        "items": itens,
    }
    if cli.get("ie"):
        pay["inscricao_estadual_destinatario"] = cli["ie"]
    doc = "".join(ch for ch in str(cli.get("doc_numero") or "") if ch.isdigit())
    if (cli.get("doc_tipo") or "").upper() == "CNPJ" and doc:
        pay["cnpj_destinatario"] = doc
    elif doc:
        pay["cpf_destinatario"] = doc
    if nfe.CNPJ_EMITENTE:
        pay["cnpj_emitente"] = nfe.CNPJ_EMITENTE
    return pay


def _campo(nome, label, valor="", larg=160, ph=""):
    return (f"<label style='font-size:12px;color:#555'>{label}<br>"
            f"<input name='{nome}' value=\"{_esc(str(valor or ''))}\" placeholder='{ph}' "
            f"style='width:{larg}px;padding:7px;border:1px solid #d7dade;border-radius:7px'/></label>")


def _card_clientes(clientes: list) -> str:
    """Cadastro + lista de clientes (usado na aba Clientes)."""
    linhas = ""
    for c in clientes:
        tel = c.get("telefone") or "&mdash;"
        apel = (f"<div class='muted' style='font-size:12px'>{_esc(c.get('apelido'))}</div>"
                if c.get("apelido") else "")
        linhas += (
            f"<tr><td>{_esc(c.get('nome') or '')}{apel}</td>"
            f"<td><b>{_esc(tel)}</b></td>"
            f"<td>{_esc((c.get('doc_tipo') or '') + ' ' + (c.get('doc_numero') or ''))}</td>"
            f"<td>{_esc((c.get('cidade') or '') + '/' + (c.get('uf') or ''))}</td>"
            f"<td><form method='post' action='/clientes/excluir' style='display:inline' "
            f"onsubmit=\"return confirm('Excluir este cliente?')\">"
            f"<input type='hidden' name='id' value='{c['id']}'/>"
            "<button class='btn ghost' style='padding:2px 8px'>x</button></form></td></tr>")
    if not linhas:
        linhas = "<tr><td colspan='5' class='muted'>Nenhum cliente cadastrado ainda.</td></tr>"
    form = (
        "<form method='post' action='/clientes/salvar' style='display:flex;gap:8px;"
        "flex-wrap:wrap;align-items:end;margin-bottom:14px'>"
        + _campo("nome", "Nome / Razao social", larg=220)
        + _campo("apelido", "Nome fantasia / apelido", larg=180)
        + ("<label style='font-size:12px;color:#555'>Tipo<br><select name='doc_tipo' "
           "style='padding:7px;border:1px solid #d7dade;border-radius:7px'>"
           "<option value='CPF'>CPF</option><option value='CNPJ'>CNPJ</option></select></label>")
        + _campo("doc_numero", "CPF/CNPJ", larg=150)
        + _campo("telefone", "Telefone", larg=130, ph="(14) 99999-9999")
        + _campo("ie", "Inscr. Estadual", larg=120)
        + _campo("email", "E-mail", larg=180)
        + _campo("cep", "CEP", larg=90)
        + _campo("rua", "Rua", larg=200)
        + _campo("numero", "Num", larg=60)
        + _campo("complemento", "Compl.", larg=110)
        + _campo("bairro", "Bairro", larg=130)
        + _campo("cidade", "Cidade", larg=140)
        + _campo("uf", "UF", larg=50)
        + "<button class='btn'>Salvar cliente</button></form>")
    return (form + "<table><tr><th>Nome</th><th>Telefone</th><th>Documento</th>"
            "<th>Cidade</th><th></th></tr>" + linhas + "</table>")


def _card_produtos_balcao(prods: list) -> str:
    """Cadastro + lista de produtos do balcao (usado na aba Produtos)."""
    linhas = ""
    for p in prods:
        linhas += (
            f"<tr><td>{_esc(p.get('nome') or '')}</td><td>{_moeda(float(p.get('preco') or 0))}</td>"
            f"<td class='muted' style='font-size:12px'>{_esc(p.get('ncm') or '')} &middot; "
            f"{_esc(p.get('cfop') or '')} &middot; {_esc(p.get('cst') or '')}</td>"
            f"<td><form method='post' action='/produtos/balcao/excluir' style='display:inline' "
            f"onsubmit=\"return confirm('Excluir este produto?')\">"
            f"<input type='hidden' name='id' value='{p['id']}'/>"
            "<button class='btn ghost' style='padding:2px 8px'>x</button></form></td></tr>")
    if not linhas:
        linhas = "<tr><td colspan='4' class='muted'>Nenhum produto de balcao cadastrado ainda.</td></tr>"
    form = (
        "<form method='post' action='/produtos/balcao/salvar' style='display:flex;gap:8px;"
        "flex-wrap:wrap;align-items:end;margin-bottom:14px'>"
        + _campo("nome", "Produto", larg=220)
        + _campo("preco", "Preco (R$)", larg=90, ph="0,00")
        + _campo("ncm", "NCM", larg=90)
        + _campo("cfop", "CFOP", larg=70)
        + _campo("cst", "CST/CSOSN", larg=90)
        + _campo("unidade", "Unid.", larg=60, ph="UN")
        + _campo("origem", "Origem", larg=60, ph="0")
        + "<button class='btn'>Salvar produto</button></form>")
    return (form + "<table><tr><th>Produto</th><th>Preco</th>"
            "<th>Fiscal (NCM &middot; CFOP &middot; CST)</th><th></th></tr>" + linhas + "</table>")


@app.get("/clientes", response_class=HTMLResponse)
def clientes_page(request: Request):
    nome, papel = _atual(request)
    corpo = (
        "<link rel='stylesheet' href='https://cdn.jsdelivr.net/npm/"
        "@tabler/icons-webfont@3.11.0/dist/tabler-icons.min.css'>"
        "<h1>Clientes</h1>"
        "<p class='muted'>Cadastro de clientes para emissao de Nota Fiscal no balcao "
        "(e futuro atendimento). O telefone fica salvo para contato.</p>"
        "<div class='card'>" + _card_clientes(balcao.listar_clientes()) + "</div>"
    )
    return _pagina(corpo, ativo="clientes", papel=papel, nome=nome)


@app.post("/clientes/salvar")
async def clientes_salvar(request: Request):
    form = await request.form()
    dados = {k: (str(form.get(k) or "").strip()) for k in balcao._CAMPOS_CLI}
    if dados.get("nome"):
        balcao.salvar_cliente(dados)
    return RedirectResponse("/clientes", status_code=303)


@app.post("/clientes/excluir")
async def clientes_excluir(request: Request, id: int = Form(...)):
    balcao.excluir_cliente(id)
    return RedirectResponse("/clientes", status_code=303)


@app.post("/produtos/balcao/salvar")
async def produtos_balcao_salvar(request: Request):
    form = await request.form()
    dados = {k: (str(form.get(k) or "").strip()) for k in balcao._CAMPOS_PROD}
    dados["preco"] = _num(dados.get("preco") or "0", 0)
    if dados.get("nome"):
        balcao.salvar_produto(dados)
    return RedirectResponse("/produtos", status_code=303)


@app.post("/produtos/balcao/excluir")
async def produtos_balcao_excluir(request: Request, id: int = Form(...)):
    balcao.excluir_produto(id)
    return RedirectResponse("/produtos", status_code=303)


@app.get("/balcao", response_class=HTMLResponse)
def balcao_page(request: Request, msg: str = ""):
    nome, papel = _atual(request)
    clientes = balcao.listar_clientes()
    prods = balcao.listar_produtos()

    aviso = ""
    if msg:
        aviso = (f"<div class='card' style='background:#EAF6F0;border-color:#bfe3d3'>{_esc(msg)}</div>")
    if not nfe.configurado():
        aviso += ("<div class='card' style='background:#FBF3D6;border-color:#ecdca0'>"
                  "<b>Emissao em modo preparacao.</b> A NF sera emitida de verdade quando o "
                  "token do Focus NFe estiver configurado (FOCUS_NFE_TOKEN no Render). "
                  "Voce ja pode cadastrar clientes e produtos.</div>")

    # ---- Emitir NF (balcao) ----
    opt_cli = "<option value=''>Selecione o cliente</option>" + "".join(
        f"<option value='{c['id']}'>{_esc(c.get('nome') or '')}"
        + (f" ({c.get('doc_numero')})" if c.get('doc_numero') else "") + "</option>"
        for c in clientes)
    opt_prod = "<option value=''>Produto...</option>" + "".join(
        f"<option value='{p['id']}'>{_esc(p.get('nome') or '')} &middot; {_moeda(float(p.get('preco') or 0))}</option>"
        for p in prods)
    linha_item = (f"<div class='item-linha' style='display:flex;gap:8px;margin-bottom:6px'>"
                  f"<select name='prod' style='flex:1;padding:7px;border:1px solid #d7dade;border-radius:7px'>{opt_prod}</select>"
                  "<input name='qtd' value='1' inputmode='decimal' style='width:70px;padding:7px;"
                  "border:1px solid #d7dade;border-radius:7px'/></div>")
    finalizar_btn = ("<button class='btn' formaction='/balcao/finalizar'>"
                     "<i class='ti ti-check'></i> Finalizar pedido</button>")
    emitir_btn = ("<button class='btn ghost' formaction='/balcao/emitir'>"
                  "<i class='ti ti-file-invoice'></i> Emitir NF</button>" if nfe.configurado()
                  else "<button class='btn ghost' formaction='/balcao/emitir' disabled "
                  "title='Configure o Focus NFe'><i class='ti ti-file-invoice'></i> Emitir NF</button>")
    card_emitir = (
        "<div class='card'><h3 style='margin-top:0'>Venda no balcao</h3>"
        "<form method='post' action='/balcao/finalizar'>"
        "<div style='margin-bottom:10px'><select name='cliente_id' required "
        "style='padding:8px;border:1px solid #d7dade;border-radius:8px;min-width:280px'>"
        + opt_cli + "</select></div>"
        "<div id='itens'>" + linha_item + "</div>"
        "<button type='button' class='btn ghost' onclick='addItem()' style='margin:4px 0 10px'>"
        "+ item</button>"
        "<div style='margin:6px 0 12px'>"
        "<label class='muted' style='font-size:13px'>Observacao</label>"
        "<textarea name='observacao' rows='2' placeholder='Ex.: retirar 2a feira, arte aprovada, "
        "pago no pix...' style='width:100%;padding:8px;border:1px solid #d7dade;border-radius:8px;"
        "resize:vertical;box-sizing:border-box'></textarea></div>"
        "<div style='display:flex;gap:10px;flex-wrap:wrap'>" + finalizar_btn + emitir_btn + "</div>"
        "</form></div>"
        "<script>function addItem(){var c=document.getElementById('itens');"
        "var n=c.firstElementChild.cloneNode(true);c.appendChild(n);}</script>"
    )

    # ---- Pedidos finalizados no balcao (reimprimir) ----
    linhas_ped = ""
    for pd in balcao.listar_pedidos(30):
        linhas_ped += (f"<tr><td>#{pd['id']}</td><td>{_esc(pd.get('cliente_nome') or '-')}</td>"
                       f"<td>{_moeda(float(pd.get('total') or 0))}</td>"
                       f"<td><a href='/balcao/imprimir?id={pd['id']}' target='_blank'>"
                       "<i class='ti ti-printer'></i> imprimir</a></td></tr>")
    if not linhas_ped:
        linhas_ped = "<tr><td colspan='4' class='muted'>Nenhum pedido finalizado ainda.</td></tr>"
    card_pedidos = ("<div class='card'><h3 style='margin-top:0'>Pedidos do balcao</h3>"
                    "<table><tr><th>#</th><th>Cliente</th><th>Total</th><th></th></tr>"
                    + linhas_ped + "</table></div>")

    # ---- Notas emitidas no balcao ----
    linhas_nf = ""
    for n in nfe.listar_balcao(50):
        links = ""
        if n.get("danfe_url"):
            links += f"<a href='{_esc(n['danfe_url'])}' target='_blank'>DANFE</a> "
        if n.get("xml_url"):
            links += f"<a href='{_esc(n['xml_url'])}' target='_blank' class='muted'>XML</a> "
        links += (f"<a class='muted' href='/nf/status?ref={quote(n.get('ref',''), safe='')}"
                  "&voltar=/balcao'>atualizar</a>")
        linhas_nf += (f"<tr><td>{_badge_nf(n.get('status'))}</td><td>{n.get('numero') or '-'}</td>"
                      f"<td>{links}</td></tr>")
    if not linhas_nf:
        linhas_nf = "<tr><td colspan='3' class='muted'>Nenhuma NF de balcao emitida ainda.</td></tr>"
    card_notas = ("<div class='card'><h3 style='margin-top:0'>Notas emitidas no balcao</h3>"
                  "<table><tr><th>Status</th><th>Numero</th><th>Arquivos</th></tr>"
                  f"{linhas_nf}</table></div>")

    atalhos = ("<div class='card' style='display:flex;gap:14px;flex-wrap:wrap;align-items:center'>"
               "<span class='muted' style='font-size:13px'>Cadastros:</span>"
               "<a class='btn ghost' href='/clientes'><i class='ti ti-users'></i> Clientes</a>"
               "<a class='btn ghost' href='/produtos'><i class='ti ti-box'></i> Produtos do balcao</a>"
               "</div>")

    corpo = (
        "<link rel='stylesheet' href='https://cdn.jsdelivr.net/npm/"
        "@tabler/icons-webfont@3.11.0/dist/tabler-icons.min.css'>"
        "<h1>Balcao</h1>"
        "<p class='muted'>Venda fora do Mercado Livre. Escolha o <b>cliente</b> e os "
        "<b>produtos</b> (cadastrados nas abas Clientes e Produtos), adicione uma observacao e "
        "clique em <b>Finalizar pedido</b> para imprimir. A <b>NF</b> usa o provedor Focus NFe.</p>"
        + aviso + atalhos + card_emitir + card_pedidos + card_notas
    )
    return _pagina(corpo, ativo="balcao", papel=papel, nome=nome)


@app.post("/balcao/emitir")
async def balcao_emitir(request: Request):
    nome, papel = _atual(request)
    form = await request.form()
    cli = balcao.obter_cliente(int(form.get("cliente_id") or 0)) or {}
    prod_ids = form.getlist("prod")
    qtds = form.getlist("qtd")
    linhas = []
    for pid, q in zip(prod_ids, qtds):
        if not str(pid).strip():
            continue
        p = balcao.obter_produto(int(pid))
        if p:
            linhas.append((p, float(_num(str(q or "1"), 1)) or 1))
    if not cli or not linhas:
        return RedirectResponse("/balcao?msg=" + quote("Escolha um cliente e ao menos um produto."),
                                status_code=303)
    try:
        pack = f"balcao-{int(datetime.now().timestamp())}"
        reg = nfe.emitir(pack, "", _nfe_payload_balcao(cli, linhas))
        usuarios.registrar(nome or "?", "nf_balcao", pack)
        msg = f"NF do balcao enviada (status: {reg.get('status')})."
    except Exception as e:
        msg = f"Nao consegui emitir agora: {e}"
    return RedirectResponse("/balcao?msg=" + quote(msg), status_code=303)


@app.post("/balcao/finalizar")
async def balcao_finalizar(request: Request):
    """Finaliza a venda do balcao: salva o pedido e abre a impressao."""
    nome, papel = _atual(request)
    form = await request.form()
    cli = balcao.obter_cliente(int(form.get("cliente_id") or 0)) or {}
    obs = str(form.get("observacao") or "").strip()
    itens = []
    total = 0.0
    for pid, q in zip(form.getlist("prod"), form.getlist("qtd")):
        if not str(pid).strip():
            continue
        p = balcao.obter_produto(int(pid))
        if not p:
            continue
        qtd = float(_num(str(q or "1"), 1)) or 1
        preco = float(p.get("preco") or 0)
        total += preco * qtd
        itens.append({"nome": p.get("nome"), "preco": preco, "qtd": qtd,
                      "unidade": p.get("unidade") or "UN", "ncm": p.get("ncm"),
                      "cfop": p.get("cfop"), "cst": p.get("cst")})
    if not cli or not itens:
        return RedirectResponse("/balcao?msg=" + quote("Escolha um cliente e ao menos um produto."),
                                status_code=303)
    pid = balcao.salvar_pedido({"cliente_id": cli.get("id"), "cliente_nome": cli.get("nome"),
                                "observacao": obs, "total": round(total, 2), "itens": itens,
                                "atendente": nome or "?"})
    usuarios.registrar(nome or "?", "balcao_pedido", str(pid))
    return RedirectResponse(f"/balcao/imprimir?id={pid}", status_code=303)


@app.get("/balcao/imprimir", response_class=HTMLResponse)
def balcao_imprimir(request: Request, id: int = 0):
    """Impressao do pedido de balcao (mesmo estilo dos pedidos do ML)."""
    pedido = balcao.obter_pedido(id)
    if not pedido:
        return HTMLResponse("<p style='font-family:Arial'>Pedido nao encontrado. "
                            "<a href='/balcao'>Voltar</a></p>")
    cli = (balcao.obter_cliente(pedido.get("cliente_id")) if pedido.get("cliente_id") else {}) or {}

    emp = store.carregar("empresa") or {}
    contas = mercadolivre.contas()
    empresa_nome = emp.get("nome") or (mercadolivre.nome_exibicao(contas[0]) if contas else "Zappe Hub")
    empresa_info = "".join(
        f"<div>{_esc(v)}</div>" for v in
        [emp.get("endereco", ""), emp.get("cnpj", ""), emp.get("telefone", "")] if v)

    linhas_cli = [f"<b>{_esc(cli.get('nome') or pedido.get('cliente_nome') or '-')}</b>"]
    if cli.get("doc_numero"):
        linhas_cli.append(_esc(f"{cli.get('doc_tipo','')} {cli.get('doc_numero','')}".strip()))
    if cli.get("rua"):
        end = f"{cli.get('rua','')}, {cli.get('numero','')}"
        if cli.get("complemento"):
            end += f" - {cli['complemento']}"
        linhas_cli.append(_esc(end))
        linhas_cli.append(_esc(f"{cli.get('bairro','')} - {cli.get('cidade','')}/"
                               f"{cli.get('uf','')} - CEP {cli.get('cep','')}"))
    if cli.get("telefone"):
        linhas_cli.append(_esc(f"Fone: {cli['telefone']}"))
    cliente_html = "<br>".join(linhas_cli)

    rows = ""
    n_itens = soma_qtd = 0
    for it in pedido.get("itens") or []:
        qtd = float(it.get("qtd") or 0)
        unit = float(it.get("preco") or 0)
        n_itens += 1
        soma_qtd += qtd
        rows += (f"<tr><td>{_esc(it.get('nome') or '-')}</td><td>{_esc(it.get('unidade') or 'UN')}</td>"
                 f"<td style='text-align:center'>{qtd:g}</td>"
                 f"<td style='text-align:right'>{_moeda(unit)}</td>"
                 f"<td style='text-align:right'>{_moeda(qtd * unit)}</td></tr>")

    obs_html = ""
    if pedido.get("observacao"):
        obs_html = ("<div class='box' style='margin-top:16px'><div class='lbl'>Observacao</div>"
                    f"{_esc(pedido['observacao'])}</div>")
    data = _data_br(datetime.fromtimestamp(pedido.get("criado_em") or 0).isoformat())

    html = f"""<!doctype html><html lang='pt-br'><meta charset='utf-8'>
<title>Pedido balcao #{pedido['id']}</title><style>
@media print {{ .noprint {{ display:none !important }} body {{ margin:0 }} }}
body {{ font-family: Arial, Helvetica, sans-serif; color:#222; max-width:820px;
       margin:20px auto; padding:0 24px; font-size:13px }}
.bar {{ display:flex; gap:10px; margin-bottom:18px }}
.btn {{ background:#2D3277; color:#fff; border:none; padding:10px 18px; border-radius:8px;
       font-size:14px; cursor:pointer; text-decoration:none }}
.btn.g {{ background:#fff; border:1px solid #cfd3da; color:#333 }}
.head {{ display:flex; justify-content:space-between; align-items:flex-start;
        border-bottom:2px solid #333; padding-bottom:12px }}
.head .emp {{ text-align:right; font-size:12px; color:#444; line-height:1.5 }}
h1.tt {{ text-align:center; font-size:20px; margin:18px 0 }}
.grid {{ display:flex; gap:14px }}
.box {{ border:1px solid #cfd3da; border-radius:6px; padding:10px 12px; flex:1; line-height:1.6 }}
.box .lbl {{ color:#888; font-size:11px; text-transform:uppercase }}
table {{ width:100%; border-collapse:collapse; margin-top:16px; font-size:12.5px }}
th {{ background:#f2f3f5; text-align:left; padding:8px; border-bottom:1px solid #ccc }}
td {{ padding:8px; border-bottom:1px solid #eee }}
.tot {{ margin-top:12px; text-align:right; line-height:1.8 }}
.tot b {{ font-size:15px }}
.ft {{ margin-top:26px; text-align:center; color:#9aa2ad; font-size:11px }}
</style>
<div class='bar noprint'>
  <button class='btn' onclick='window.print()'>&#128424; Imprimir / Salvar PDF</button>
  <a class='btn g' href='/balcao'>Voltar ao balcao</a>
</div>
<div class='head'>
  <div><div style='font-size:18px;font-weight:700'>{_esc(empresa_nome)}</div></div>
  <div class='emp'>{empresa_info}</div>
</div>
<h1 class='tt'>Pedido de balcao #{pedido['id']}</h1>
<div class='grid'>
  <div class='box'><div class='lbl'>Cliente</div>{cliente_html}</div>
  <div class='box' style='max-width:280px'>
    <div class='lbl'>Numero do pedido</div><b>#{pedido['id']}</b>
    <div class='lbl' style='margin-top:6px'>Data</div>{data}
    <div class='lbl' style='margin-top:6px'>Atendente</div>{_esc(pedido.get('atendente') or '-')}
  </div>
</div>
<table>
  <tr><th>Descricao do produto</th><th>Un.</th>
      <th style='text-align:center'>Qtd</th><th style='text-align:right'>Valor unit.</th>
      <th style='text-align:right'>Valor total</th></tr>
  {rows}
</table>
{obs_html}
<div class='tot'>
  N&ordm; de itens: {n_itens} &nbsp;&middot;&nbsp; Soma das qtds: {soma_qtd:g}<br>
  <b>Total do pedido: {_moeda(float(pedido.get('total') or 0))}</b>
</div>
<div class='ft'>Gerado pelo Zappe Hub</div>
</html>"""
    return HTMLResponse(html)


@app.get("/imprimir", response_class=HTMLResponse)
def pedido_imprimir(request: Request, pack: str = "", conta: str = ""):
    """Pagina de impressao do pedido (o navegador salva como PDF).
    Rota /imprimir (NAO /pedido/imprimir) para nao colidir com /pedido/{id} do Bling."""
    contas = mercadolivre.contas()
    if not contas:
        return RedirectResponse("/ml/login")
    acc = next((a for a in contas if str(a["user_id"]) == conta), None) or contas[0]
    uid = str(acc["user_id"])
    try:
        o = mercadolivre.obter_pedido(pack, token=acc) or mercadolivre.pedido_do_pack(pack, token=acc) or {}
    except (RuntimeError, httpx.HTTPError):
        o = {}
    if not o:
        return HTMLResponse("<p style='font-family:Arial'>Pedido nao encontrado. "
                            "<a href='/vendas'>Voltar</a></p>")
    try:
        env = mercadolivre.dados_envio(o, user_id=uid, token=acc)
    except Exception:
        env = {}

    emp = store.carregar("empresa") or {}
    empresa_nome = emp.get("nome") or mercadolivre.nome_exibicao(acc)
    empresa_info = "".join(
        f"<div>{_esc(v)}</div>" for v in
        [emp.get("endereco", ""), emp.get("cnpj", ""), emp.get("telefone", "")] if v)

    comprador = (o.get("buyer") or {}).get("nickname") or "-"
    oid = str(o.get("id") or "")
    pack_id = str(o.get("pack_id") or "")

    # pacote com varios pedidos do mesmo comprador -> imprime todos juntos
    if pack_id and pack_id != oid:
        try:
            pedidos = mercadolivre.orders_do_pack(pack_id, user_id=uid, token=acc) or [o]
        except (RuntimeError, httpx.HTTPError):
            pedidos = [o]
    else:
        pedidos = [o]
    varios = len(pedidos) > 1

    ids = " + ".join(str(p.get("id") or "") for p in pedidos)
    codigo = (f"pacote {pack_id}" if varios else oid) + (
        f"<div class='muted' style='font-size:11px;color:#888'>{ids}</div>" if varios else "")
    data = _data_br(o.get("date_created"))

    # bloco do cliente (nome/endereco do envio quando houver)
    linhas_cli = [f"<b>{_esc(env.get('nome') or comprador)}</b>"]
    if env.get("rua"):
        end = f"{env.get('rua','')}, {env.get('numero','')}"
        if env.get("complemento"):
            end += f" - {env['complemento']}"
        linhas_cli.append(_esc(end))
        linhas_cli.append(_esc(f"{env.get('bairro','')} - {env.get('cidade','')}/"
                               f"{env.get('estado','')} - CEP {env.get('cep','')}"))
    if env.get("telefone"):
        linhas_cli.append(_esc(f"Fone: {env['telefone']}"))
    cliente_html = "<br>".join(linhas_cli)

    rows = ""
    n_itens = soma_qtd = 0
    total_ped = 0.0
    for ped in pedidos:
        total_ped += float(ped.get("total_amount") or 0)
        for it in (ped.get("order_items") or []):
            item = it.get("item") or {}
            desc = item.get("title") or "-"
            cod = item.get("seller_custom_field") or item.get("id") or "-"
            qtd = float(it.get("quantity") or 0)
            unit = float(it.get("unit_price") or 0)
            n_itens += 1
            soma_qtd += qtd
            rows += (f"<tr><td>{_esc(desc)}</td><td>{_esc(str(cod))}</td><td>UN</td>"
                     f"<td style='text-align:center'>{qtd:g}</td>"
                     f"<td style='text-align:right'>{_moeda(unit)}</td>"
                     f"<td style='text-align:right'>{_moeda(qtd * unit)}</td></tr>")

    titulo_doc = f"Pacote {pack_id}" if varios else f"Pedido {oid}"
    html = f"""<!doctype html><html lang='pt-br'><meta charset='utf-8'>
<title>{titulo_doc}</title><style>
@media print {{ .noprint {{ display:none !important }} body {{ margin:0 }} }}
body {{ font-family: Arial, Helvetica, sans-serif; color:#222; max-width:820px;
       margin:20px auto; padding:0 24px; font-size:13px }}
.bar {{ display:flex; gap:10px; margin-bottom:18px }}
.btn {{ background:#2D3277; color:#fff; border:none; padding:10px 18px; border-radius:8px;
       font-size:14px; cursor:pointer; text-decoration:none }}
.btn.g {{ background:#fff; border:1px solid #cfd3da; color:#333 }}
.head {{ display:flex; justify-content:space-between; align-items:flex-start;
        border-bottom:2px solid #333; padding-bottom:12px }}
.head .emp {{ text-align:right; font-size:12px; color:#444; line-height:1.5 }}
h1.tt {{ text-align:center; font-size:20px; margin:18px 0 }}
.grid {{ display:flex; gap:14px }}
.box {{ border:1px solid #cfd3da; border-radius:6px; padding:10px 12px; flex:1; line-height:1.6 }}
.box .lbl {{ color:#888; font-size:11px; text-transform:uppercase }}
table {{ width:100%; border-collapse:collapse; margin-top:16px; font-size:12.5px }}
th {{ background:#f2f3f5; text-align:left; padding:8px; border-bottom:1px solid #ccc }}
td {{ padding:8px; border-bottom:1px solid #eee }}
.tot {{ margin-top:12px; text-align:right; line-height:1.8 }}
.tot b {{ font-size:15px }}
.ft {{ margin-top:26px; text-align:center; color:#9aa2ad; font-size:11px }}
</style>
<div class='bar noprint'>
  <button class='btn' onclick='window.print()'>&#128424; Imprimir / Salvar PDF</button>
  <a class='btn g' href='javascript:history.back()'>Voltar</a>
</div>
<div class='head'>
  <div><div style='font-size:18px;font-weight:700'>{_esc(empresa_nome)}</div></div>
  <div class='emp'>{empresa_info}</div>
</div>
<h1 class='tt'>{titulo_doc}</h1>
<div class='grid'>
  <div class='box'><div class='lbl'>Cliente</div>{cliente_html}</div>
  <div class='box' style='max-width:280px'>
    <div class='lbl'>{"Pedidos do pacote" if varios else "Numero do pedido"}</div><b>{codigo}</b>
    <div class='lbl' style='margin-top:6px'>Data do pedido</div>{data}
    <div class='lbl' style='margin-top:6px'>Enviar ate</div>{_data_br(env.get('enviar_ate')) if env.get('enviar_ate') else '-'}
    <div class='lbl' style='margin-top:6px'>Loja</div>{_esc(mercadolivre.nome_exibicao(acc))}
  </div>
</div>
<table>
  <tr><th>Descricao do produto</th><th>Codigo</th><th>Un.</th>
      <th style='text-align:center'>Qtd</th><th style='text-align:right'>Valor unit.</th>
      <th style='text-align:right'>Valor total</th></tr>
  {rows}
</table>
<div class='tot'>
  N&ordm; de itens: {n_itens} &nbsp;&middot;&nbsp; Soma das qtds: {soma_qtd:g}<br>
  <b>{"Total do pacote" if varios else "Total do pedido"}: {_moeda(total_ped)}</b>
</div>
<div class='ft'>Gerado pelo Zappe Hub</div>
</html>"""
    return HTMLResponse(html)


@app.get("/vendas/diag", response_class=HTMLResponse)
def vendas_diag(request: Request, cod: str = ""):
    """Diagnostico: dado 1+ codigos, mostra se o pedido existe, data, dono e se
    aparece na busca por periodo. Ajuda a achar por que um pedido 'nao aparece'."""
    nome, papel = _atual(request)
    if papel != "admin":
        return RedirectResponse("/inbox")
    contas = mercadolivre.contas()
    hoje = date.today()
    de = (hoje - timedelta(days=90)).isoformat()
    ate = hoje.isoformat()
    codigos = [c.strip() for c in cod.replace(",", " ").split() if c.strip()]

    def _dump_ship(o, uid, acc) -> str:
        sid = (o.get("shipping") or {}).get("id")
        if not sid:
            return "          (pedido sem shipping.id)"
        try:
            s = mercadolivre.get(f"/shipments/{sid}", user_id=uid, token=acc)
        except Exception as e:
            code = getattr(getattr(e, "response", None), "status_code", "")
            return f"          erro shipment {sid}: {type(e).__name__} {code}"
        return (f"          shipment {sid} status={s.get('status')}\n"
                f"          lead_time={str(s.get('lead_time'))[:500]}\n"
                f"          shipping_option={str(s.get('shipping_option'))[:300]}")

    out: list[str] = []
    for code in codigos:
        out.append(f"===== codigo {code} =====")
        achou = False
        for acc in contas:
            uid = str(acc["user_id"])
            loja = mercadolivre.nome_exibicao(acc)
            try:
                o = mercadolivre.obter_pedido(code, token=acc)
            except Exception as e:
                out.append(f"  [{loja}] erro GET /orders/{code}: {type(e).__name__}")
                continue
            if not o:
                # nao e pedido nesta conta -> tenta como PACK (carrinho de varios itens)
                try:
                    pk = mercadolivre.get(f"/packs/{code}", user_id=uid, token=acc)
                except Exception:
                    pk = None
                if pk and pk.get("id"):
                    ords = [str(x.get("id")) for x in (pk.get("orders") or [])]
                    out.append(f"  [{loja}] e um PACK (carrinho). pedidos dentro: {ords}  "
                               f"status={pk.get('status')}")
                    achou = True
                    try:
                        o2 = mercadolivre.obter_pedido(ords[0], token=acc) if ords else None
                        if o2:
                            out.append(_dump_ship(o2, uid, acc))
                    except Exception:
                        pass
                else:
                    out.append(f"  [{loja}] nao e pedido nem pack desta conta (404)")
                continue
            achou = True
            oid = str(o.get("id"))
            pack = str(o.get("pack_id") or "")
            dt = str(o.get("date_created") or "")[:19]
            seller = str((o.get("seller") or {}).get("id") or "")
            comprador = (o.get("buyer") or {}).get("nickname", "-")
            out.append(f"  [{loja}] ACHADO  id={oid}  pack_id={pack}  status={o.get('status')}")
            out.append(f"          data={dt}  seller={seller}  comprador={comprador}")
            try:
                pedidos = mercadolivre.pedidos_periodo(de, ate, user_id=uid, token=acc)
                ids = {str(p.get("id")) for p in pedidos}
                packs = {str(p.get("pack_id") or "") for p in pedidos}
                na_lista = oid in ids or (pack and pack in packs) or code in ids
                out.append(f"          aparece na busca 90d ({len(pedidos)} pedidos)? "
                           + ("SIM" if na_lista else "NAO"))
            except Exception as e:
                out.append(f"          erro ao listar periodo: {type(e).__name__}")
            out.append(_dump_ship(o, uid, acc))
        if not achou:
            out.append("  -> nao encontrado em NENHUMA conta conectada.")
        out.append("")
    inner = "\n".join(out).replace("<", "&lt;")
    corpo = (
        "<h1>Diagnostico de pedidos</h1>"
        "<p class='muted'>Cole os codigos que nao aparecem (separados por espaco) e clique Verificar.</p>"
        "<form method='get' action='/vendas/diag' style='display:flex;gap:8px;margin:10px 0'>"
        f"<input name='cod' value='{cod}' placeholder='2000013781425337 2000013782161365 ...' "
        "style='flex:1;padding:9px;border:1px solid #d7dade;border-radius:8px'/>"
        "<button class='btn'>Verificar</button></form>"
        + (f"<pre style='white-space:pre-wrap;font-size:12px;background:#fff;border:1px solid "
           f"#e6e8eb;border-radius:10px;padding:14px'>{inner}</pre>" if codigos else "")
    )
    return _pagina(corpo, ativo="vendas", papel=papel, nome=nome)


# --------------------------------------------------------------------------- #
# Atendimento WhatsApp: base de conhecimento da IA (texto + upload de documento)
# --------------------------------------------------------------------------- #
def _esc(s: str) -> str:
    return (s or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _extrair_texto(nome: str, dados: bytes) -> str:
    """Extrai texto de um documento enviado (txt/md/csv, pdf ou docx)."""
    n = (nome or "").lower()
    try:
        if n.endswith((".txt", ".md", ".csv")):
            return dados.decode("utf-8", errors="ignore")
        if n.endswith(".pdf"):
            import pypdf
            leitor = pypdf.PdfReader(io.BytesIO(dados))
            return "\n".join((p.extract_text() or "") for p in leitor.pages)
        if n.endswith(".docx"):
            import docx
            doc = docx.Document(io.BytesIO(dados))
            return "\n".join(p.text for p in doc.paragraphs)
    except Exception:
        return ""
    try:
        return dados.decode("utf-8", errors="ignore")
    except Exception:
        return ""


def _base_conhecimento() -> dict:
    b = store.carregar("base_conhecimento") or {}
    return {"texto": b.get("texto", ""), "atualizado": b.get("atualizado", ""),
            "origem": b.get("origem", "")}


@app.get("/whatsapp", response_class=HTMLResponse)
def whatsapp_page(request: Request):
    nome, papel = _atual(request)
    if papel != "admin":
        return RedirectResponse("/inbox")
    base = _base_conhecimento()
    texto = base["texto"]
    n_chars = len(texto)
    ia_ok = config.is_ia_configured()

    ia_badge = ("<span class='badge' style='background:#E1F5EE;color:#0F6E56'>IA conectada</span>"
                if ia_ok else
                "<span class='badge' style='background:#FCF1DD;color:#C77700'>IA nao configurada</span>")
    status = (
        "<div class='card'>"
        "<h3 style='margin-top:0'>Status</h3>"
        "<div style='display:flex;flex-direction:column;gap:10px'>"
        "<div>&#128241; <b>WhatsApp:</b> <span class='pill'>em breve</span> "
        "vamos conectar o numero oficial (Meta). Enquanto isso, o assistente ja pode ajudar na "
        "<a href='/inbox'>Caixa de entrada</a> do Mercado Livre.</div>"
        f"<div>&#129302; <b>Assistente IA:</b> {ia_badge} "
        + ("&mdash; tudo pronto para sugerir respostas." if ia_ok else
           "&mdash; falta a chave da API da Claude (<code>ANTHROPIC_API_KEY</code>) no servidor. "
           "Crie em console.anthropic.com e me avise que eu te ajudo a colocar.")
        + "</div></div></div>"
    )

    atualizado_html = "<span></span>"
    if base["atualizado"]:
        d10 = base["atualizado"][:10]
        data_fmt = f"{d10[8:10]}/{d10[5:7]}/{d10[0:4]}" if len(d10) == 10 else d10
        origem = f" &middot; de <b>{_esc(base['origem'])}</b>" if base["origem"] else ""
        atualizado_html = (f"<span class='muted' style='font-size:12px'>Atualizado em "
                           f"{data_fmt}{origem} &middot; {n_chars} caracteres</span>")

    card_base = (
        "<div class='card'>"
        "<h3 style='margin-top:0'>&#128218; Base de conhecimento</h3>"
        "<p class='muted' style='margin-top:-4px'>A IA responde <b>apenas</b> com base no que "
        "estiver aqui. Se a pergunta nao estiver na base, ela encaminha para um atendente "
        "&mdash; assim voce limita o atendimento ao que autorizou.</p>"
        "<form method='post' action='/whatsapp/upload' enctype='multipart/form-data' "
        "style='display:flex;gap:8px;align-items:center;flex-wrap:wrap;"
        "background:#f4f5f7;border-radius:10px;padding:12px;margin-bottom:14px'>"
        "<i class='ti ti-upload'></i>"
        "<input type='file' name='arquivo' accept='.pdf,.docx,.txt,.md,.csv' required "
        "style='flex:1;min-width:220px'/>"
        "<button class='btn'>Enviar documento</button>"
        "<span class='muted' style='font-size:11px;flex-basis:100%'>"
        "PDF, DOCX ou TXT. O texto do arquivo entra na base abaixo (voce pode editar depois de subir).</span>"
        "</form>"
        "<form method='post' action='/whatsapp/base'>"
        "<textarea name='texto' rows='16' style='width:100%;padding:12px;border:1px solid #d7dade;"
        "border-radius:10px;font-family:inherit;font-size:13.5px;line-height:1.5' "
        "placeholder='Cole aqui o manual de atendimento: prazos, formas de pagamento, como enviar "
        "a arte, politica de troca, perguntas frequentes...'>"
        f"{_esc(texto)}</textarea>"
        "<div style='display:flex;justify-content:space-between;align-items:center;margin-top:10px'>"
        f"{atualizado_html}"
        "<button class='btn'>Salvar base</button></div>"
        "</form>"
        "</div>"
    )

    proximo = (
        "<div class='card' style='background:#EEEDFE;border-color:#d9d5fb'>"
        "<h3 style='margin-top:0'>Proximo passo</h3>"
        "<p style='margin:0'>Com a base preenchida e a chave da IA ligada, eu adiciono o botao "
        "<b>\"Sugerir resposta\"</b> na conversa: a IA le a base + os dados do pedido e monta um "
        "rascunho; voce revisa e envia. <b>Nada e enviado sozinho.</b></p></div>"
    )

    corpo = (
        "<link rel='stylesheet' href='https://cdn.jsdelivr.net/npm/"
        "@tabler/icons-webfont@3.11.0/dist/tabler-icons.min.css'>"
        "<h1>Atendimento WhatsApp</h1>"
        "<p class='muted'>Monte aqui o \"manual\" que a IA usa para atender. Modo copiloto: "
        "a IA <b>sugere</b>, o humano revisa e envia.</p>"
        f"{status}{card_base}{proximo}"
    )
    return _pagina(corpo, ativo="whatsapp", papel=papel, nome=nome)


@app.post("/whatsapp/base")
def whatsapp_base_salvar(request: Request, texto: str = Form("")):
    if _atual(request)[1] != "admin":
        return RedirectResponse("/inbox")
    atual = store.carregar("base_conhecimento") or {}
    store.salvar("base_conhecimento", {
        "texto": texto, "atualizado": datetime.now().isoformat(),
        "origem": atual.get("origem", ""),
    })
    return RedirectResponse("/whatsapp", status_code=303)


@app.post("/whatsapp/upload")
async def whatsapp_upload(request: Request, arquivo: UploadFile = File(...)):
    if _atual(request)[1] != "admin":
        return RedirectResponse("/inbox")
    dados = await arquivo.read()
    texto = _extrair_texto(arquivo.filename or "", dados)
    if texto.strip():
        store.salvar("base_conhecimento", {
            "texto": texto, "atualizado": datetime.now().isoformat(),
            "origem": arquivo.filename or "",
        })
    return RedirectResponse("/whatsapp", status_code=303)


# --------------------------------------------------------------------------- #
# Backup: exporta os dados do app num JSON e restaura de volta (admin)
# --------------------------------------------------------------------------- #
@app.get("/backup", response_class=HTMLResponse)
def backup_page(request: Request, ok: str = ""):
    nome, papel = _atual(request)
    if papel != "admin":
        return RedirectResponse("/inbox")
    aviso = ("<div class='card' style='background:#E1F5EE;border-color:#9fdcc7'>"
             "Backup restaurado com sucesso.</div>" if ok == "1" else "")
    corpo = (
        "<h1>Backup</h1>"
        "<p class='muted'>Baixe uma copia dos seus dados (custos de produtos, fluxos, "
        "atendentes por pedido, usuarios, categorias, custos fixos, consumo de IA e "
        "configuracoes). <b>Nao inclui</b> os tokens do Mercado Livre/Bling (recuperaveis "
        "reconectando as contas).</p>"
        f"{aviso}"
        "<div class='card'><h3 style='margin-top:0'>&#11015; Exportar</h3>"
        "<p class='muted' style='margin-top:-4px'>Baixa um arquivo JSON com todos os dados. "
        "Guarde no seu computador ou no Drive.</p>"
        "<a class='btn' href='/backup/exportar'>Baixar backup (JSON)</a></div>"
        "<div class='card'><h3 style='margin-top:0'>&#11014; Restaurar</h3>"
        "<p class='muted' style='margin-top:-4px'>Suba um arquivo de backup para repor os dados. "
        "Ele <b>atualiza/insere</b> por cima do que existe (nao apaga o resto).</p>"
        "<form method='post' action='/backup/restaurar' enctype='multipart/form-data' "
        "style='display:flex;gap:8px;align-items:center;flex-wrap:wrap' "
        "onsubmit=\"return confirm('Restaurar este backup por cima dos dados atuais?')\">"
        "<input type='file' name='arquivo' accept='.json' required/>"
        "<button class='btn ghost'>Restaurar backup</button></form></div>"
        "<p class='muted' style='font-size:12px'>Dica: o banco (Neon) tambem tem restauracao "
        "automatica por tempo (Point-in-Time), e o codigo fica no GitHub &mdash; este backup e "
        "uma copia extra na sua mao.</p>"
    )
    return _pagina(corpo, ativo="backup", papel=papel, nome=nome)


@app.get("/backup/exportar")
def backup_exportar(request: Request):
    if _atual(request)[1] != "admin":
        return RedirectResponse("/inbox")
    dump = backup.exportar()
    conteudo = json.dumps(dump, ensure_ascii=False, default=str, indent=2)
    fn = f"zappehub-backup-{date.today().isoformat()}.json"
    return Response(conteudo, media_type="application/json",
                    headers={"Content-Disposition": f"attachment; filename=\"{fn}\""})


@app.post("/backup/restaurar")
async def backup_restaurar(request: Request, arquivo: UploadFile = File(...)):
    if _atual(request)[1] != "admin":
        return RedirectResponse("/inbox")
    try:
        dump = json.loads((await arquivo.read()).decode("utf-8"))
        backup.importar(dump)
    except Exception:
        return _pagina("<h1>Backup</h1><div class='card' style='background:#FCEBEB;"
                       "border-color:#f2b8b8'>Arquivo de backup invalido.</div>"
                       "<p><a href='/backup'>&larr; voltar</a></p>", ativo="backup",
                       papel="admin", nome=_atual(request)[0])
    return RedirectResponse("/backup?ok=1", status_code=303)


