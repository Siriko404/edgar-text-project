import os
import re
import sys
from dotenv import load_dotenv
from typing import Dict, Any, Optional
from fastapi import Depends, FastAPI, HTTPException, Request, Response, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from pydantic import BaseModel, Field, field_validator
import time
from collections import defaultdict

# Import monitoring and logging
from logging_config import setup_logging, get_logger
from monitoring import metrics, PerformanceMonitor, start_background_monitoring

# Import authentication
from auth import (
    get_current_user_optional,
    get_user_rate_limit,
    initialize_demo_keys
)
from auth_endpoints import auth_router

# --- Application Setup ---
# Load environment variables from .env file
load_dotenv()

# Setup logging
log_level = os.getenv("LOG_LEVEL", "INFO")
log_file = os.getenv("LOG_FILE")
setup_logging(log_level=log_level, log_file=log_file)
logger = get_logger("edgar_text.api")

# This import must happen AFTER load_dotenv() to ensure its own environment
# variables are loaded. We add a comment to tell flake8 to ignore this style rule.
import main  # noqa: E402
import config  # noqa: E402

# --- Configuration ---
# External service keys are read lazily by the modules that need them;
# endpoints fail explicitly when their service is unconfigured.

# API Metadata
app = FastAPI(
    title="Edgar-Text API",
    description="Provides textual analysis on corporate filings with authentication and monitoring.",
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
)

# Include authentication router
app.include_router(auth_router)

# --- Security Middleware ---
# Origins and hosts are configured via CORS_ORIGINS / TRUSTED_HOSTS.
# "testserver" is accepted only under pytest so TestClient works.
_cors_origins = list(config.CORS_ORIGINS)
_trusted_hosts = list(config.TRUSTED_HOSTS)
if "pytest" in sys.modules and "testserver" not in _trusted_hosts:
    _trusted_hosts.append("testserver")

# CORS configuration
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)

# Trusted host middleware (prevent host header attacks)
app.add_middleware(
    TrustedHostMiddleware,
    allowed_hosts=_trusted_hosts,
)

# --- Rate Limiting ---
# Tiered per-identity rate limiting. Anonymous callers share a per-IP bucket;
# authenticated callers get the bucket of their tier (see docs/API.md).
# Buckets live in the shared disk cache so multiple workers enforce one limit.
rate_limit_storage = defaultdict(list)
RATE_LIMIT_REQUESTS = config.RATE_LIMIT_REQUESTS  # requests per window
RATE_LIMIT_WINDOW = config.RATE_LIMIT_WINDOW  # seconds


def _bucket_load(key: str) -> list:
    try:
        return list(main.cache.get(f"ratelimit:{key}") or [])
    except Exception:
        return list(rate_limit_storage.get(key, []))


def _bucket_save(key: str, hits: list) -> None:
    rate_limit_storage[key] = hits
    try:
        main.cache.set(f"ratelimit:{key}", hits, expire=RATE_LIMIT_WINDOW * 2)
    except Exception as e:
        logger.warning(f"Could not persist rate bucket {key}: {e}")


def check_rate_limit(client_ip: str) -> bool:
    """Simple in-memory rate limiting (legacy fixed bucket, kept for compat)."""
    return _check_bucket(f"ip:{client_ip}", RATE_LIMIT_REQUESTS, RATE_LIMIT_WINDOW)


def _check_bucket(key: str, limit: int, window: int) -> bool:
    """Record a hit in the named bucket; True when under the limit."""
    now = time.time()
    hits = [t for t in _bucket_load(key) if now - t < window]

    # Check if under limit
    if len(hits) >= limit:
        _bucket_save(key, hits)
        return False

    # Add current request
    _bucket_save(key, hits + [now])
    return True


def _rate_limit_identity(user: Optional[Dict[str, Any]], client_ip: str) -> str:
    """Bucket key: authenticated identity when present, else caller IP."""
    if user:
        return f"{user.get('auth_type', 'auth')}:{user.get('user_id', 'unknown')}"
    return f"ip:{client_ip}"


def enforce_tiered_rate_limit(
    response: Response, user: Optional[Dict[str, Any]], client_ip: str
) -> None:
    """Enforce the caller's tier limit and set X-RateLimit-* headers.

    Raises 429 when the bucket is exhausted; always sets headers.
    """
    limit = get_user_rate_limit(user)
    key = _rate_limit_identity(user, client_ip)
    now = time.time()
    hits = [t for t in _bucket_load(key) if now - t < RATE_LIMIT_WINDOW]
    remaining = max(0, limit - len(hits))
    reset = int(now + RATE_LIMIT_WINDOW)
    response.headers["X-RateLimit-Limit"] = str(limit)
    response.headers["X-RateLimit-Remaining"] = str(remaining)
    response.headers["X-RateLimit-Reset"] = str(reset)
    if len(hits) >= limit:
        _bucket_save(key, hits)
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Rate limit exceeded. Please try again later.",
        )
    _bucket_save(key, hits + [now])
    response.headers["X-RateLimit-Remaining"] = str(max(0, limit - len(hits) - 1))


# --- Load Quantized ONNX Model at Startup ---
# This is a global variable that holds our model in memory
sentiment_pipeline = {}


@app.on_event("startup")
def load_model():
    """
    Loads the ONNX model and tokenizer into memory when the API starts.
    This is best practice to avoid reloading the model on every request.
    Heavy ML imports are lazy so test collection does not require torch.
    """
    import config

    logger.info("Starting model loading process")
    model_path = config.MODEL_PATH
    if not os.path.isdir(model_path):
        logger.error(
            f"Model directory not found at {model_path}. "
            "Set MODEL_PATH or run scripts/check_assets.py for setup. "
            "Sentiment endpoint will return 503 until the model is provisioned."
        )
    else:
        from optimum.onnxruntime import ORTModelForSequenceClassification
        from transformers import AutoTokenizer

        with PerformanceMonitor("model_loading"):
            tokenizer = AutoTokenizer.from_pretrained(model_path)
            model = ORTModelForSequenceClassification.from_pretrained(model_path)
            sentiment_pipeline["tokenizer"] = tokenizer
            sentiment_pipeline["model"] = model

    # Start background monitoring
    start_background_monitoring()

    # Initialize demo API keys for testing
    demo_keys = initialize_demo_keys()
    logger.info(f"API startup complete - model loaded, monitoring started, {len(demo_keys)} demo keys created")


# --- Pydantic Models ---
# For validating incoming request data
class SentimentRequest(BaseModel):
    text: str = Field(
        ...,
        min_length=1,
        max_length=5000,
        description="Text to analyze (1-5000 characters)",
    )

    @field_validator("text")
    @classmethod
    def validate_text_content(cls, v):
        """Validate text content for security."""
        if not v.strip():
            raise ValueError("Text cannot be empty or whitespace only")

        # Basic XSS prevention
        if re.search(r"<script|javascript:|data:", v, re.IGNORECASE):
            raise ValueError("Text contains potentially malicious content")

        return v.strip()


class TickerRequest(BaseModel):
    """Validation for ticker symbols."""

    ticker: str = Field(
        ...,
        min_length=1,
        max_length=10,
        pattern=r"^[A-Z]{1,5}$",
        description="Stock ticker symbol (1-5 uppercase letters)",
    )


# For structuring the API response
class SentimentResponse(BaseModel):
    label: str
    score: float


# --- API Endpoints ---
@app.get("/", tags=["Status"])
def read_root():
    """Root endpoint to check API status."""
    metrics.record_counter("health_check_requests")
    logger.info("Health check requested")
    return {"status": "ok", "message": "Edgar-Text API is running"}


@app.get("/metrics", tags=["Monitoring"])
def get_metrics():
    """Get application metrics and performance data."""
    logger.info("Metrics requested")
    return metrics.get_summary()


@app.post("/analyze/sentiment", tags=["Analysis"], response_model=SentimentResponse)
async def analyze_sentiment(
    request: SentimentRequest,
    client_request: Request,
    response: Response,
    user: Optional[Dict[str, Any]] = Depends(get_current_user_optional),
):
    """
    Analyzes the sentiment of a given block of text using the optimized DistilFinBERT model.
    Authentication is optional but increases the rate limit (see docs/API.md).
    """
    # Tiered rate limiting check (sets X-RateLimit-* headers)
    enforce_tiered_rate_limit(response, user, client_request.client.host)

    if not sentiment_pipeline:
        raise HTTPException(status_code=503, detail="Model is not loaded yet.")

    try:
        tokenizer = sentiment_pipeline["tokenizer"]
        model = sentiment_pipeline["model"]

        # Tokenize the input text
        inputs = tokenizer(
            request.text, return_tensors="pt", truncation=True, max_length=512
        )

        # Perform inference
        outputs = model(**inputs)

        # Get the predicted label (0: negative, 1: neutral, 2: positive)
        prediction = outputs.logits.argmax().item()

        # Get the score (softmax to get probabilities)
        probabilities = outputs.logits.softmax(dim=-1)
        score = probabilities[0][prediction].item()

        # Map prediction index to label name
        label = model.config.id2label[prediction]

        return {"label": label.upper(), "score": score}

    except Exception as e:
        # Log the error for debugging
        print(f"ERROR during sentiment analysis: {e}")
        raise HTTPException(
            status_code=500, detail="Internal server error during sentiment analysis."
        )


@app.get("/analyze/{ticker}", tags=["Analysis"])
def get_analysis(
    ticker: str,
    client_request: Request,
    response: Response,
    user: Optional[Dict[str, Any]] = Depends(get_current_user_optional),
):
    """
    Triggers the full filing analysis for a given company ticker.
    Authentication is optional but increases the rate limit (see docs/API.md).
    (This is now a synchronous function to fix the 'await' error)
    """
    # Tiered rate limiting check (sets X-RateLimit-* headers)
    enforce_tiered_rate_limit(response, user, client_request.client.host)

    # Validate ticker format
    if not re.match(r"^[A-Z]{1,5}$", ticker.upper()):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid ticker format. Must be 1-5 uppercase letters.",
        )

    try:
        # No 'await' is needed because analyze_company is a regular function
        analysis_result = main.analyze_company(ticker.upper())
        return analysis_result
    except ValueError as e:
        if "SEC_API_KEY" in str(e):
            raise HTTPException(status_code=500, detail=str(e))
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"An unexpected error occurred: {e}"
        )


def _get_length_bucket(length: int) -> str:
    """Categorize text length into buckets for metrics."""
    if length < 100:
        return "small"
    elif length < 1000:
        return "medium"
    elif length < 3000:
        return "large"
    else:
        return "xlarge"
