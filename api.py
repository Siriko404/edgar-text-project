import os
import re
import stripe
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Header, Request, status
from fastapi.responses import RedirectResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from pydantic import BaseModel, Field, validator
from optimum.onnxruntime import ORTModelForSequenceClassification
from transformers import AutoTokenizer
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

# --- Configuration & Model Loading ---
# API Keys and secrets
STRIPE_SECRET_KEY = os.getenv("STRIPE_SECRET_KEY")
STRIPE_PRICE_ID = os.getenv("STRIPE_PRICE_ID")
STRIPE_WEBHOOK_SECRET = os.getenv("STRIPE_WEBHOOK_SECRET")

# Check for required secrets
if not STRIPE_SECRET_KEY:
    raise ValueError("STRIPE_SECRET_KEY not found. Ensure it is in your .env file.")

stripe.api_key = STRIPE_SECRET_KEY

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
# CORS configuration
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "http://localhost:8000",
    ],  # Add your frontend URLs
    allow_credentials=True,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)

# Trusted host middleware (prevent host header attacks)
app.add_middleware(
    TrustedHostMiddleware,
    allowed_hosts=["localhost", "127.0.0.1", "*.example.com"],  # Update for production
)

# --- Rate Limiting ---
rate_limit_storage = defaultdict(list)
RATE_LIMIT_REQUESTS = 100  # requests per window
RATE_LIMIT_WINDOW = 3600  # 1 hour in seconds


def check_rate_limit(client_ip: str) -> bool:
    """Simple in-memory rate limiting."""
    now = time.time()
    # Clean old requests
    rate_limit_storage[client_ip] = [
        req_time
        for req_time in rate_limit_storage[client_ip]
        if now - req_time < RATE_LIMIT_WINDOW
    ]

    # Check if under limit
    if len(rate_limit_storage[client_ip]) >= RATE_LIMIT_REQUESTS:
        return False

    # Add current request
    rate_limit_storage[client_ip].append(now)
    return True


# --- Load Quantized ONNX Model at Startup ---
# This is a global variable that holds our model in memory
sentiment_pipeline = {}


@app.on_event("startup")
def load_model():
    """
    Loads the ONNX model and tokenizer into memory when the API starts.
    This is best practice to avoid reloading the model on every request.
    """
    logger.info("Starting model loading process")
    with PerformanceMonitor("model_loading"):
        model_path = "./models/distilfinbert_onnx_q8"
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

    @validator("text")
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
        regex=r"^[A-Z]{1,5}$",
        description="Stock ticker symbol (1-5 uppercase letters)",
    )


# For structuring the API response
class SentimentResponse(BaseModel):
    label: str
    score: float


# --- In-memory Event Store (for webhook idempotency) ---
PROCESSED_EVENTS = set()


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
async def analyze_sentiment(request: SentimentRequest, client_request: Request):
    """
    Analyzes the sentiment of a given block of text using the optimized DistilFinBERT model.
    """
    # Rate limiting check
    client_ip = client_request.client.host
    if not check_rate_limit(client_ip):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Rate limit exceeded. Please try again later.",
        )

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
def get_analysis(ticker: str, client_request: Request):
    """
    Triggers the full filing analysis for a given company ticker.
    (This is now a synchronous function to fix the 'await' error)
    """
    # Rate limiting check
    client_ip = client_request.client.host
    if not check_rate_limit(client_ip):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Rate limit exceeded. Please try again later.",
        )

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
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"An unexpected error occurred: {e}"
        )


@app.post("/create-checkout-session", tags=["Payments"])
def create_checkout_session():
    """
    Creates a Stripe Checkout session for the Info Tier product.
    (This remains unchanged from Day 12)
    """
    try:
        checkout_session = stripe.checkout.Session.create(
            line_items=[
                {
                    "price": STRIPE_PRICE_ID,
                    "quantity": 1,
                },
            ],
            mode="payment",
            success_url="http://localhost:8000/success.html",
            cancel_url="http://localhost:8000/cancel.html",
        )
        # Use a 303 See Other redirect, which is standard for POST -> GET redirects
        return RedirectResponse(checkout_session.url, status_code=303)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/webhook", tags=["Payments"])
async def stripe_webhook(request: Request, stripe_signature: str = Header(None)):
    """
    Handles incoming webhooks from Stripe to manage payment events.
    (This remains unchanged from Day 13)
    """
    payload = await request.body()
    try:
        event = stripe.Webhook.construct_event(
            payload=payload, sig_header=stripe_signature, secret=STRIPE_WEBHOOK_SECRET
        )
    except ValueError as e:
        # Invalid payload
        raise HTTPException(status_code=400, detail=f"Invalid payload: {e}")
    except stripe.error.SignatureVerificationError as e:
        # Invalid signature
        raise HTTPException(status_code=400, detail=f"Invalid signature: {e}")

    # --- Idempotency Check ---
    event_id = event.get("id")
    if event_id in PROCESSED_EVENTS:
        print(f"-> Webhook event {event_id} already processed. Skipping.")
        return {"status": "already processed"}

    # Handle the event
    if event["type"] == "checkout.session.completed":
        session = event["data"]["object"]
        print(f"-> Payment successful for session: {session.get('id')}")
        # TODO: Provision access to the user (e.g., generate API key)
    else:
        print(f"-> Unhandled event type: {event['type']}")

    # Add the event to our processed set
    PROCESSED_EVENTS.add(event_id)

    return {"status": "success"}


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
