"""Shared pytest configuration: hermetic defaults and custom markers."""

import os

# Hermetic defaults so importing app modules never requires real credentials.
# Individual tests override with mocks as needed.
os.environ.setdefault("SEC_API_KEY", "test_sec_key")
os.environ.setdefault("STRIPE_SECRET_KEY", "sk_test_dummy")
os.environ.setdefault("STRIPE_PRICE_ID", "price_dummy")
os.environ.setdefault("STRIPE_WEBHOOK_SECRET", "whsec_dummy")
os.environ.setdefault("JWT_SECRET_KEY", "test_jwt_secret")


def pytest_addoption(parser):
    """Add command line options for pytest."""
    parser.addoption(
        "--integration",
        action="store_true",
        default=False,
        help="Run integration tests",
    )


import pytest  # noqa: E402


@pytest.fixture(autouse=True)
def _clear_disk_cache():
    """Clear persistent caches and rate buckets so tests never leak state."""
    try:
        import main

        main.cache.clear()
    except Exception:
        pass
    try:
        import api

        api.rate_limit_storage.clear()
    except Exception:
        pass
    yield
    try:
        import main

        main.cache.clear()
    except Exception:
        pass
    try:
        import api

        api.rate_limit_storage.clear()
    except Exception:
        pass
