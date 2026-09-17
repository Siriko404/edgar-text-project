"""
Authentication middleware for Edgar-Text API.
"""

import os
import jwt
import hashlib
import secrets
from datetime import datetime, timedelta
from typing import Optional, Dict, Any
from fastapi import HTTPException, status, Depends, Security
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel

from logging_config import get_logger
from monitoring import metrics

logger = get_logger("edgar_text.auth")

# JWT Configuration
JWT_SECRET_KEY = os.getenv("JWT_SECRET_KEY", secrets.token_urlsafe(32))
if not os.getenv("JWT_SECRET_KEY"):
    logger.warning(
        "JWT_SECRET_KEY not set; using an ephemeral secret. "
        "Set JWT_SECRET_KEY in .env for restarts and multi-worker deployments."
    )
JWT_ALGORITHM = "HS256"
JWT_EXPIRATION_HOURS = int(os.getenv("JWT_EXPIRATION_HOURS", "24"))

# API Key Configuration
API_KEY_PREFIX = "edgar_"
VALID_API_KEYS = set()  # In production, load from database

# Security scheme
security = HTTPBearer(auto_error=False)


class TokenData(BaseModel):
    """JWT token data model."""
    user_id: str
    email: Optional[str] = None
    tier: str = "free"  # free, basic, premium
    expires_at: datetime


class APIKeyData(BaseModel):
    """API key data model."""
    key_id: str
    user_id: str
    tier: str = "free"
    rate_limit: int = 100  # requests per hour
    created_at: datetime
    last_used: Optional[datetime] = None


def generate_api_key(user_id: str, tier: str = "free") -> str:
    """Generate a new API key for a user."""
    # Create unique identifier
    timestamp = datetime.utcnow().isoformat()
    raw_key = f"{user_id}:{tier}:{timestamp}:{secrets.token_urlsafe(16)}"

    # Hash for security
    key_hash = hashlib.sha256(raw_key.encode()).hexdigest()[:24]
    api_key = f"{API_KEY_PREFIX}{key_hash}"

    # In production, store in database
    key_data = APIKeyData(
        key_id=key_hash,
        user_id=user_id,
        tier=tier,
        rate_limit=_get_rate_limit_for_tier(tier),
        created_at=datetime.utcnow()
    )

    # For demo purposes, store in memory
    VALID_API_KEYS.add(api_key)

    logger.info(f"Generated API key for user {user_id}", extra={
        "user_id": user_id,
        "tier": tier,
        "key_prefix": api_key[:12] + "..."
    })

    return api_key


def _get_rate_limit_for_tier(tier: str) -> int:
    """Get rate limit based on user tier."""
    limits = {
        "free": 100,
        "basic": 1000,
        "premium": 10000,
    }
    return limits.get(tier, 100)


def create_jwt_token(user_id: str, email: str = None, tier: str = "free") -> str:
    """Create a JWT token for a user."""
    expires_at = datetime.utcnow() + timedelta(hours=JWT_EXPIRATION_HOURS)

    payload = {
        "user_id": user_id,
        "email": email,
        "tier": tier,
        "exp": expires_at,
        "iat": datetime.utcnow(),
        "iss": "edgar-text-api"
    }

    token = jwt.encode(payload, JWT_SECRET_KEY, algorithm=JWT_ALGORITHM)

    logger.info(f"Created JWT token for user {user_id}", extra={
        "user_id": user_id,
        "tier": tier,
        "expires_at": expires_at.isoformat()
    })

    return token


def verify_jwt_token(token: str) -> TokenData:
    """Verify and decode a JWT token."""
    try:
        payload = jwt.decode(token, JWT_SECRET_KEY, algorithms=[JWT_ALGORITHM])

        token_data = TokenData(
            user_id=payload["user_id"],
            email=payload.get("email"),
            tier=payload.get("tier", "free"),
            expires_at=datetime.fromtimestamp(payload["exp"])
        )

        # Check if token is expired
        if token_data.expires_at < datetime.utcnow():
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Token has expired"
            )

        return token_data

    except jwt.ExpiredSignatureError:
        logger.warning("JWT token expired")
        metrics.record_counter("auth_token_expired")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token has expired"
        )
    except jwt.InvalidTokenError as e:
        logger.warning(f"Invalid JWT token: {e}")
        metrics.record_counter("auth_invalid_token")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token"
        )


def verify_api_key(api_key: str) -> APIKeyData:
    """Verify an API key."""
    if not api_key.startswith(API_KEY_PREFIX):
        logger.warning(f"Invalid API key format: {api_key[:12]}...")
        metrics.record_counter("auth_invalid_api_key_format")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid API key format"
        )

    # In production, lookup in database
    if api_key not in VALID_API_KEYS:
        logger.warning(f"API key not found: {api_key[:12]}...")
        metrics.record_counter("auth_api_key_not_found")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid API key"
        )

    # For demo purposes, return mock data
    # In production, fetch from database
    key_data = APIKeyData(
        key_id=api_key[len(API_KEY_PREFIX):],
        user_id="demo_user",
        tier="basic",
        rate_limit=1000,
        created_at=datetime.utcnow() - timedelta(days=30),
        last_used=datetime.utcnow()
    )

    logger.info(f"Valid API key used", extra={
        "key_prefix": api_key[:12] + "...",
        "user_id": key_data.user_id,
        "tier": key_data.tier
    })

    metrics.record_counter("auth_api_key_success", labels={"tier": key_data.tier})
    return key_data


async def get_current_user(credentials: Optional[HTTPAuthorizationCredentials] = Security(security)) -> Dict[str, Any]:
    """
    Dependency to get current authenticated user.
    Supports both JWT tokens and API keys.
    """
    if not credentials:
        metrics.record_counter("auth_no_credentials")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required",
            headers={"WWW-Authenticate": "Bearer"}
        )

    token = credentials.credentials

    # Try API key first
    if token.startswith(API_KEY_PREFIX):
        try:
            api_key_data = verify_api_key(token)
            return {
                "user_id": api_key_data.user_id,
                "tier": api_key_data.tier,
                "rate_limit": api_key_data.rate_limit,
                "auth_type": "api_key"
            }
        except HTTPException:
            pass  # Fall through to JWT verification

    # Try JWT token
    try:
        token_data = verify_jwt_token(token)
        return {
            "user_id": token_data.user_id,
            "email": token_data.email,
            "tier": token_data.tier,
            "rate_limit": _get_rate_limit_for_tier(token_data.tier),
            "auth_type": "jwt"
        }
    except HTTPException:
        metrics.record_counter("auth_failed")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authentication credentials",
            headers={"WWW-Authenticate": "Bearer"}
        )


async def get_current_user_optional(credentials: Optional[HTTPAuthorizationCredentials] = Security(security)) -> Optional[Dict[str, Any]]:
    """
    Optional authentication dependency.
    Returns user data if authenticated, None otherwise.
    """
    if not credentials:
        return None

    try:
        return await get_current_user(credentials)
    except HTTPException:
        return None


def require_tier(required_tier: str):
    """
    Dependency factory to require a specific user tier.
    Usage: @app.get("/premium-endpoint", dependencies=[Depends(require_tier("premium"))])
    """
    async def check_tier(current_user: Dict[str, Any] = Depends(get_current_user)):
        tier_hierarchy = {"free": 0, "basic": 1, "premium": 2}

        user_tier_level = tier_hierarchy.get(current_user["tier"], 0)
        required_tier_level = tier_hierarchy.get(required_tier, 999)

        if user_tier_level < required_tier_level:
            logger.warning(f"Insufficient tier access", extra={
                "user_id": current_user["user_id"],
                "user_tier": current_user["tier"],
                "required_tier": required_tier
            })
            metrics.record_counter("auth_insufficient_tier", labels={
                "user_tier": current_user["tier"],
                "required_tier": required_tier
            })
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"This endpoint requires {required_tier} tier access"
            )

        return current_user

    return check_tier


# Rate limiting with authentication
def get_user_rate_limit(user_data: Optional[Dict[str, Any]]) -> int:
    """Get rate limit for authenticated or anonymous user."""
    if user_data:
        return user_data.get("rate_limit", 100)
    else:
        return int(os.getenv("ANONYMOUS_RATE_LIMIT", "10"))  # Very low for anonymous


# Demo function to initialize some API keys for testing
def initialize_demo_keys():
    """Initialize demo API keys for testing purposes."""
    demo_keys = [
        generate_api_key("demo_user_1", "free"),
        generate_api_key("demo_user_2", "basic"),
        generate_api_key("demo_user_3", "premium"),
    ]

    logger.info(f"Initialized {len(demo_keys)} demo API keys")
    return demo_keys