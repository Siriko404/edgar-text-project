"""
Authentication endpoints for Edgar-Text API.
"""

from fastapi import APIRouter, HTTPException, status, Depends
from pydantic import BaseModel, EmailStr
from typing import Optional, Dict, Any
from datetime import datetime

from auth import (
    get_current_user,
    require_tier,
    generate_api_key,
    create_jwt_token,
    VALID_API_KEYS
)
from logging_config import get_logger
from monitoring import metrics

logger = get_logger("edgar_text.auth_endpoints")

# Create router for authentication endpoints
auth_router = APIRouter(prefix="/auth", tags=["Authentication"])


class LoginRequest(BaseModel):
    """User login request."""
    email: EmailStr
    password: str


class SignupRequest(BaseModel):
    """User signup request."""
    email: EmailStr
    password: str
    tier: str = "free"


class APIKeyRequest(BaseModel):
    """API key generation request."""
    name: Optional[str] = None
    tier: str = "free"


class TokenResponse(BaseModel):
    """Authentication token response."""
    access_token: str
    token_type: str = "bearer"
    expires_in: int
    user_id: str
    tier: str


class APIKeyResponse(BaseModel):
    """API key generation response."""
    api_key: str
    key_id: str
    tier: str
    rate_limit: int
    created_at: datetime


class UserInfoResponse(BaseModel):
    """User information response."""
    user_id: str
    email: Optional[str]
    tier: str
    rate_limit: int
    auth_type: str


@auth_router.post("/login", response_model=TokenResponse)
async def login(request: LoginRequest):
    """
    User login endpoint backed by the persisted user store.
    """
    logger.info(f"Login attempt for email: {request.email}")

    import auth_store

    user = auth_store.verify_user(request.email, request.password)
    if user is None:
        metrics.record_counter("auth_login_failed")
        logger.warning(f"Failed login attempt for email: {request.email}")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password"
        )

    token = create_jwt_token(
        user_id=user["user_id"], email=user["email"], tier=user["tier"]
    )

    metrics.record_counter("auth_login_success", labels={"tier": user["tier"]})
    logger.info(f"Successful login for user: {user['user_id']}")

    return TokenResponse(
        access_token=token,
        expires_in=24 * 3600,  # 24 hours
        user_id=user["user_id"],
        tier=user["tier"]
    )


@auth_router.post("/signup", response_model=TokenResponse)
async def signup(request: SignupRequest):
    """
    User signup endpoint backed by the persisted user store.
    """
    logger.info(f"Signup attempt for email: {request.email}")

    import auth_store

    if request.tier not in ("free", "basic", "premium"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Unknown tier. Choose free, basic, or premium.",
        )
    if request.tier == "premium":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Premium requires payment. Sign up free, then POST /create-checkout-session.",
        )
    try:
        user = auth_store.create_user(request.email, request.password, request.tier)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=str(e)
        )

    token = create_jwt_token(
        user_id=user["user_id"], email=user["email"], tier=user["tier"]
    )

    metrics.record_counter("auth_signup_success", labels={"tier": user["tier"]})
    logger.info(f"Successful signup for user: {user['user_id']}")

    return TokenResponse(
        access_token=token,
        expires_in=24 * 3600,  # 24 hours
        user_id=user["user_id"],
        tier=user["tier"]
    )


@auth_router.post("/api-key", response_model=APIKeyResponse)
async def create_api_key(
    request: APIKeyRequest,
    current_user: Dict[str, Any] = Depends(get_current_user)
):
    """
    Generate a new API key for the authenticated user.
    """
    logger.info("API key creation requested", extra={
        "user_id": current_user["user_id"],
        "requested_tier": request.tier
    })

    # Ensure user can only create keys for their tier or lower
    tier_hierarchy = {"free": 0, "basic": 1, "premium": 2}
    user_tier_level = tier_hierarchy.get(current_user["tier"], 0)
    requested_tier_level = tier_hierarchy.get(request.tier, 0)

    if requested_tier_level > user_tier_level:
        metrics.record_counter("auth_api_key_tier_denied")
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Cannot create {request.tier} API key with {current_user['tier']} account"
        )

    api_key = generate_api_key(current_user["user_id"], request.tier)

    # In production, store key metadata in database
    key_data = APIKeyResponse(
        api_key=api_key,
        key_id=api_key.split("_")[1][:8],  # First 8 chars of key ID
        tier=request.tier,
        rate_limit=current_user["rate_limit"],
        created_at=datetime.utcnow()
    )

    metrics.record_counter("auth_api_key_created", labels={"tier": request.tier})
    logger.info(f"API key created for user: {current_user['user_id']}")

    return key_data


@auth_router.get("/me", response_model=UserInfoResponse)
async def get_user_info(current_user: Dict[str, Any] = Depends(get_current_user)):
    """
    Get information about the currently authenticated user.
    """
    logger.info(f"User info requested for: {current_user['user_id']}")

    return UserInfoResponse(
        user_id=current_user["user_id"],
        email=current_user.get("email"),
        tier=current_user["tier"],
        rate_limit=current_user["rate_limit"],
        auth_type=current_user["auth_type"]
    )


@auth_router.get("/demo-keys")
async def get_demo_keys():
    """
    Get demo API keys for testing (development only).
    In production, this endpoint should be removed.
    """
    if len(VALID_API_KEYS) == 0:
        from auth import initialize_demo_keys
        demo_keys = initialize_demo_keys()
    else:
        demo_keys = list(VALID_API_KEYS)

    logger.info("Demo keys requested")
    metrics.record_counter("auth_demo_keys_requested")

    return {
        "demo_keys": demo_keys[:3],  # Only show first 3 for security
        "note": "These are demo keys for testing. In production, use proper authentication.",
        "usage": "Include any of these keys in the Authorization header as 'Bearer <key>'"
    }


@auth_router.delete("/api-key/{key_id}")
async def revoke_api_key(
    key_id: str,
    current_user: Dict[str, Any] = Depends(get_current_user)
):
    """
    Revoke an API key.
    In production, this would mark the key as revoked in the database.
    """
    logger.info("API key revocation requested", extra={
        "user_id": current_user["user_id"],
        "key_id": key_id
    })

    # Demo implementation - in production, mark as revoked in database
    import auth_store

    revoked = auth_store.delete_api_key_by_id(key_id)
    if not revoked:
        # Legacy fallback for pre-persistence in-memory keys
        for api_key in list(VALID_API_KEYS):
            if key_id in api_key:
                VALID_API_KEYS.remove(api_key)
                revoked = True
                break

    if revoked:
        metrics.record_counter("auth_api_key_revoked")
        logger.info(f"API key revoked for user: {current_user['user_id']}")
        return {"message": "API key revoked successfully"}
    else:
        metrics.record_counter("auth_api_key_revoke_failed")
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="API key not found"
        )


# Premium tier example endpoint
@auth_router.get("/premium/advanced-metrics", dependencies=[Depends(require_tier("premium"))])
async def get_advanced_metrics(current_user: Dict[str, Any] = Depends(get_current_user)):
    """
    Example premium endpoint that requires premium tier access.
    """
    logger.info(f"Premium metrics requested by: {current_user['user_id']}")
    metrics.record_counter("auth_premium_endpoint_accessed")

    return {
        "message": "This is premium content",
        "user_tier": current_user["tier"],
        "advanced_metrics": {
            "detailed_performance": "Available for premium users",
            "custom_dashboards": "Enabled",
            "priority_support": "Active"
        }
    }
