"""App de teste: autentica no Bling e lista os pedidos reais numa telinha.

Rodar:
    uvicorn app.main:app --reload
Depois abra http://localhost:8000 no navegador.
"""
import secrets
from datetime import date

import httpx
from pathlib import Path

from fastapi import FastAPI, Form, Request
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse, Response
from starlette.middleware.sessions import SessionMiddleware

from . import bling, categorias, config, mercadolivre, store, usuarios

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
    # 1) usuarios da equipe (banco)
    u = usuarios.autenticar(usuario.strip(), senha)
    if u:
        request.session.update({"auth": True, "nome": u["nome"], "papel": u["papel"]})
        return RedirectResponse("/", status_code=303)
    # 2) usuario mestre (env) - sempre admin, rede de seguranca
    if (config.APP_PASSWORD and secrets.compare_digest(usuario.strip(), config.APP_USER)
            and secrets.compare_digest(senha, config.APP_PASSWORD)):
        request.session.update({"auth": True, "nome": config.APP_USER, "papel": "admin"})
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
    admin_links = ""
    if papel == "admin":
        admin_links = (lk("/resultado", "Resultado", "resultado")
                       + lk("/usuarios", "Equipe", "usuarios")
                       + lk("/desempenho", "Desempenho", "desempenho"))
    user_chip = (f"<span class='muted' style='font-size:12px;margin-right:4px'>"
                 f"<i class='ti ti-user'></i> {nome}</span>" if nome else "")
    nav = (
        "<div class='nav'>"
        f"<a class='brand' href='/'>{_ICONE}<span>{_MARCA}</span></a>"
        "<div class='links' style='display:flex;align-items:center'>"
        + lk("/inbox", "Caixa de entrada", "inbox")
        + lk("/perguntas", "Perguntas", "perguntas")
        + lk("/pedidos", "Pedidos (Bling)", "pedidos")
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
    # se a conversa aberta nao esta na pagina atual, busca direto (sempre abre)
    if selecionado is None and pack and conta:
        acc = next((a for a in contas if str(a["user_id"]) == conta), None)
        if acc:
            o = mercadolivre.obter_pedido(pack, token=acc)
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
def desempenho(request: Request):
    nome, papel = _atual(request)
    if papel != "admin":
        return RedirectResponse("/inbox")
    res = usuarios.resumo()
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
    for l in usuarios.listar_log(200):
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
        "(Quando tiver o custo no Bling, da para puxar o real.)</div></div>"
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


@app.get("/resultado", response_class=HTMLResponse)
def resultado(request: Request, de: str = "", ate: str = ""):
    nome, papel = _atual(request)
    if papel != "admin":
        return RedirectResponse("/inbox")
    cfg = _preco_cfg()
    hoje = date.today()
    de = de or hoje.replace(day=1).isoformat()
    ate = ate or hoje.isoformat()

    linhas = ""
    n_pedidos = 0
    t_venda = t_com = t_frete = t_arec = t_custo = t_imp = t_liq = 0.0
    for acc in mercadolivre.contas():
        uid = str(acc["user_id"])
        try:
            pedidos = mercadolivre.pedidos_periodo(de, ate, user_id=uid, token=acc)
        except (RuntimeError, httpx.HTTPStatusError):
            pedidos = []
        for o in pedidos:
            n_pedidos += 1
            venda = float(o.get("total_amount") or 0)
            if not venda:
                venda = sum(float(it.get("unit_price") or 0) * float(it.get("quantity") or 0)
                            for it in (o.get("order_items") or []))
            comissao = sum(float(it.get("sale_fee") or 0) for it in (o.get("order_items") or []))
            frete = cfg["frete"]
            a_receber = venda - comissao - frete  # o que o ML deposita
            custo = venda * cfg["custo_pct"] / 100
            imposto = venda * cfg["imposto_pct"] / 100
            liquido = a_receber - custo - imposto
            margem = (liquido / venda * 100) if venda else 0
            t_venda += venda; t_com += comissao; t_frete += frete
            t_arec += a_receber; t_custo += custo; t_imp += imposto; t_liq += liquido
            cor = "#0F6E56" if liquido >= 0 else "#A32D2D"
            produtos = o.get("order_items") or []
            titulo = (produtos[0].get("item") or {}).get("title", "-") if produtos else "-"
            linhas += (
                f"<tr><td>{_data_br(o.get('date_created'))}</td><td>{o.get('id','-')}</td>"
                f"<td>{titulo[:32]}</td><td>{_moeda(venda)}</td><td>{_moeda(comissao)}</td>"
                f"<td>{_moeda(frete)}</td><td style='font-weight:500'>{_moeda(a_receber)}</td>"
                f"<td>{_moeda(custo)}</td><td>{_moeda(imposto)}</td>"
                f"<td style='color:{cor};font-weight:500'>{_moeda(liquido)}</td>"
                f"<td style='color:{cor}'>{margem:.0f}%</td></tr>"
            )
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


