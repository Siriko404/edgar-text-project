"""Centralized environment configuration for Edgar-Text API.

All documented environment variables are parsed here so that
`.env.example`, `DEPLOYMENT.md`, and runtime behavior stay consistent.
Importing this module never raises for missing optional values; use
`validate_required()` at startup or in health checks when strictness
is needed.
"""

import os


def _get_list(name: str, default: str) -> list:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return [item.strip() for item in default.split(",") if item.strip()]
    return [item.strip() for item in raw.split(",") if item.strip()]


# --- External services ---
SEC_API_KEY = os.getenv("SEC_API_KEY", "")
STRIPE_SECRET_KEY = os.getenv("STRIPE_SECRET_KEY", "")
STRIPE_PRICE_ID = os.getenv("STRIPE_PRICE_ID", "")
STRIPE_WEBHOOK_SECRET = os.getenv("STRIPE_WEBHOOK_SECRET", "")

# --- Auth ---
JWT_SECRET_KEY = os.getenv("JWT_SECRET_KEY", "")
JWT_SECRET_GENERATED = not bool(JWT_SECRET_KEY)
JWT_EXPIRATION_HOURS = int(os.getenv("JWT_EXPIRATION_HOURS", "24"))

# --- Production middleware / rate limiting ---
CORS_ORIGINS = _get_list(
    "CORS_ORIGINS", "http://localhost:3000,http://localhost:8000"
)
TRUSTED_HOSTS = _get_list(
    "TRUSTED_HOSTS", "localhost,127.0.0.1,*.example.com"
)
RATE_LIMIT_REQUESTS = int(os.getenv("RATE_LIMIT_REQUESTS", "100"))
RATE_LIMIT_WINDOW = int(os.getenv("RATE_LIMIT_WINDOW", "3600"))
ANONYMOUS_RATE_LIMIT = int(os.getenv("ANONYMOUS_RATE_LIMIT", "10"))

# --- Analysis assets ---
LM_DICTIONARY_PATH = os.getenv(
    "LM_DICTIONARY_PATH",
    "data/Loughran-McDonald_MasterDictionary_1993-2024.csv",
)
MODEL_PATH = os.getenv("MODEL_PATH", "./models/distilfinbert_onnx_q8")

# --- App ---
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
LOG_FILE = os.getenv("LOG_FILE")


def validate_required() -> list:
    """Return names of missing required values (empty when configured)."""
    missing = []
    if not SEC_API_KEY:
        missing.append("SEC_API_KEY")
    if not STRIPE_SECRET_KEY:
        missing.append("STRIPE_SECRET_KEY")
    return missing
