import os
import re
import sys
from dotenv import load_dotenv

# Load .env FIRST so every module imported below sees configured values
# (notably auth.JWT_SECRET_KEY, which is read at import time).
load_dotenv()

from typing import Dict, Any, Optional  # noqa: E402
from fastapi import (  # noqa: E402
    Depends,
    FastAPI,
    HTTPException,
    Request,
    Response,
    status,
)
from fastapi.middleware.cors import CORSMiddleware  # noqa: E402
from fastapi.middleware.trustedhost import TrustedHostMiddleware  # noqa: E402
from pydantic import BaseModel, Field, field_validator  # noqa: E402

# Import monitoring and logging
from logging_config import setup_logging, get_logger  # noqa: E402
from monitoring import (  # noqa: E402
    metrics,
    PerformanceMonitor,
    start_background_monitoring,
)

# Import authentication
from auth import (  # noqa: E402
    get_current_user,
    get_current_user_optional,
    initialize_demo_keys,
)
from auth_endpoints import auth_router  # noqa: E402
from ratelimit import (  # noqa: E402, F401
    enforce_tiered_rate_limit,
    # Re-exported so tests can reset buckets:
    rate_limit_storage,
)

# --- Application Setup ---

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
# Single enforcement point lives in ratelimit.py (imported above).
# rate_limit_storage is re-exported here so tests can reset buckets.

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

    # Demo account and keys exist only when ENABLE_DEMO_ACCOUNT=1
    demo_keys = initialize_demo_keys()
    logger.info(
        f"API startup complete - model loaded, monitoring started, {len(demo_keys)} demo keys created"
    )


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
def get_metrics(user: Dict[str, Any] = Depends(get_current_user)):
    """Get application metrics and performance data (authentication required)."""
    logger.info("Metrics requested")
    return metrics.get_summary()


@app.get("/ready", tags=["Status"])
def readiness():
    """Readiness probe: reports whether the service can do useful work.

    `/` stays a cheap liveness check; orchestration and deploy scripts
    should gate on this endpoint instead.
    """
    checks = {}
    checks["sec_api_key"] = bool(os.getenv("SEC_API_KEY"))
    try:
        positive_words, negative_words = main.load_lm_dictionary()
        checks["dictionary"] = bool(positive_words or negative_words)
    except Exception:
        checks["dictionary"] = False
    checks["model"] = bool(sentiment_pipeline)
    try:
        import auth_store

        auth_store.load_store()
        checks["auth_store"] = True
    except Exception:
        checks["auth_store"] = False
    ready = all(checks.values())
    return {"ready": ready, "checks": checks}


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
        if isinstance(analysis_result, dict) and "error" in analysis_result:
            raise HTTPException(
                status_code=int(analysis_result.get("status", 500)),
                detail=analysis_result["error"],
            )
        return analysis_result
    except HTTPException:
        raise
    except ValueError as e:
        if "SEC_API_KEY" in str(e):
            logger.error(f"Filing analysis is not configured: {e}")
            raise HTTPException(
                status_code=500,
                detail="Filing analysis is not configured on this server.",
            )
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.exception(f"Unexpected error analysing {ticker}: {e}")
        raise HTTPException(status_code=500, detail="An unexpected error occurred.")


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
