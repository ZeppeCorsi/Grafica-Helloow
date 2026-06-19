# Bling Hub — teste de atendimento

Projeto mínimo em Python (FastAPI) que autentica na **API v3 do Bling** via OAuth 2.0
e lista os **pedidos reais** numa telinha. É o primeiro passo para o hub de atendimento
unificado dos e-commerces.

## 1. Pré-requisitos

- Python 3.10+ instalado
- Uma conta no Bling com acesso ao painel de desenvolvedor

## 2. Criar o aplicativo no Bling

1. Entre no Bling → **Cadastros → Aplicativos** (painel do desenvolvedor).
2. Crie um aplicativo do tipo **OAuth**.
3. No campo de redirecionamento, cadastre **exatamente**:
   `http://localhost:8000/callback`
4. Anote o `client_id` e o `client_secret`.
5. Garanta que o app tenha permissão para **Pedidos de venda**.

## 3. Configurar o projeto

```bash
cd "C:\Users\Giuseppe\Grafica Betinho"
python -m venv .venv
.venv\Scripts\activate          # Windows (PowerShell/CMD)
pip install -r requirements.txt
copy .env.example .env           # Windows  (no Linux/Mac: cp .env.example .env)
```

Abra o `.env` e preencha `BLING_CLIENT_ID` e `BLING_CLIENT_SECRET`.

## 4. Rodar

```bash
uvicorn app.main:app --reload
```

Abra http://localhost:8000 no navegador:

1. Clique em **Conectar ao Bling** → você é levado ao Bling para autorizar.
2. Após autorizar, o Bling redireciona de volta e o token é salvo em `token.json`.
3. Você cai na lista de **pedidos reais** (`/pedidos`).

## Como funciona (resumo)

```
navegador → /login → Bling (autoriza) → /callback → troca code por token
          → /pedidos → GET /pedidos/vendas → tabela
```

- `app/bling.py` — cliente da API (OAuth, refresh automático do token, busca de pedidos)
- `app/main.py` — telas (`/`, `/login`, `/callback`, `/pedidos`)
- `app/config.py` — lê o `.env`

O `access_token` expira em ~6h; o código renova sozinho usando o `refresh_token`.

## Próximos passos

- Mapear o campo de **canal/loja** de cada pedido para os 10 e-commerces.
- Detalhar um pedido (`GET /pedidos/vendas/{id}`) com itens e rastreio.
- Plugar o WhatsApp (Cloud API da Meta) para responder o cliente.

> Não versione `.env` nem `token.json` (já estão no `.gitignore`).
