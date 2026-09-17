"""Shared tiered rate limiting (single enforcement point).

Anonymous callers share a per-IP bucket; authenticated callers get the
bucket of their tier (see docs/API.md). Buckets live in the shared disk
cache so multiple workers enforce one limit, with an in-memory mirror as
fallback. Both api.py and auth_endpoints.py enforce through here.
"""

import time
from collections import defaultdict
from typing import Any, Dict, Optional

from fastapi import HTTPException, Response, status

import config
from auth import get_user_rate_limit
from logging_config import get_logger

logger = get_logger("edgar_text.ratelimit")

rate_limit_storage: Dict[str, list] = defaultdict(list)
RATE_LIMIT_REQUESTS = config.RATE_LIMIT_REQUESTS  # requests per window
RATE_LIMIT_WINDOW = config.RATE_LIMIT_WINDOW  # seconds

_cache = None


def _get_cache():
    """Disk cache shared with the app (lazy so import never fails)."""
    global _cache
    if _cache is None:
        from diskcache import Cache

        _cache = Cache("cache_directory")
    return _cache


def _bucket_load(key: str) -> list:
    try:
        return list(_get_cache().get(f"ratelimit:{key}") or [])
    except Exception:
        return list(rate_limit_storage.get(key, []))


def _bucket_save(key: str, hits: list) -> None:
    rate_limit_storage[key] = hits
    try:
        _get_cache().set(f"ratelimit:{key}", hits, expire=RATE_LIMIT_WINDOW * 2)
    except Exception as e:
        logger.warning(f"Could not persist rate bucket {key}: {e}")


def check_rate_limit(client_ip: str) -> bool:
    """Legacy fixed-bucket check, kept for compatibility."""
    return _check_bucket(f"ip:{client_ip}", RATE_LIMIT_REQUESTS, RATE_LIMIT_WINDOW)


def _check_bucket(key: str, limit: int, window: int) -> bool:
    """Record a hit in the named bucket; True when under the limit."""
    now = time.time()
    hits = [t for t in _bucket_load(key) if now - t < window]
    if len(hits) >= limit:
        _bucket_save(key, hits)
        return False
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
