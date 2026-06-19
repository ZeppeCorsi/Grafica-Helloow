"""Carrega as configuracoes do app a partir do arquivo .env."""
import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")

CLIENT_ID = os.getenv("BLING_CLIENT_ID", "")
CLIENT_SECRET = os.getenv("BLING_CLIENT_SECRET", "")
REDIRECT_URI = os.getenv("BLING_REDIRECT_URI", "http://localhost:8000/callback")

# Endpoints da API v3 do Bling
AUTHORIZE_URL = "https://www.bling.com.br/Api/v3/oauth/authorize"
TOKEN_URL = "https://www.bling.com.br/Api/v3/oauth/token"
API_BASE = "https://api.bling.com.br/Api/v3"

# Onde guardamos o token depois de autenticar (nao versionar este arquivo).
TOKEN_FILE = BASE_DIR / "token.json"


def is_configured() -> bool:
    return bool(CLIENT_ID and CLIENT_SECRET)


# --------------------------------------------------------------------------- #
# Mercado Livre (mensagens dos compradores)
# --------------------------------------------------------------------------- #
ML_CLIENT_ID = os.getenv("ML_CLIENT_ID", "")
ML_CLIENT_SECRET = os.getenv("ML_CLIENT_SECRET", "")
# ATENCAO: o Mercado Livre exige HTTPS. Em teste local, use a URL do ngrok.
ML_REDIRECT_URI = os.getenv("ML_REDIRECT_URI", "https://localhost:8000/ml/callback")

ML_AUTHORIZE_URL = "https://auth.mercadolivre.com.br/authorization"
ML_TOKEN_URL = "https://api.mercadolibre.com/oauth/token"
ML_API_BASE = "https://api.mercadolibre.com"

TOKEN_FILE_ML = BASE_DIR / "token_ml.json"


def is_ml_configured() -> bool:
    return bool(ML_CLIENT_ID and ML_CLIENT_SECRET)


# --------------------------------------------------------------------------- #
# Login simples (HTTP Basic). Se APP_PASSWORD estiver vazio, a protecao fica
# DESLIGADA (uso local). Em producao defina APP_USER e APP_PASSWORD.
# --------------------------------------------------------------------------- #
APP_USER = os.getenv("APP_USER", "admin")
APP_PASSWORD = os.getenv("APP_PASSWORD", "")
