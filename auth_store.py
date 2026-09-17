"""File-persisted auth store: users and API keys survive restarts.

Default location ``./data/auth_store.json`` (override with AUTH_STORE_PATH).
The file is JSON ``{"users": {...}, "api_keys": {...}}``. Every mutation
rewrites the whole file, so entries are visible to all worker processes
on the next read. Passwords are stored as PBKDF2 hashes, never plaintext.
API keys are stored under their SHA-256 lookup hash, never plaintext: the
full key is shown once at creation and cannot be recovered from the file.
"""

import hashlib
import json
import os
import secrets
import tempfile
import time
from contextlib import contextmanager

try:
    import fcntl
except ImportError:  # Windows: no POSIX locks; atomic replace still applies
    fcntl = None

TIERS = ("free", "basic", "premium")


def store_path() -> str:
    return os.getenv("AUTH_STORE_PATH", os.path.join("data", "auth_store.json"))


def _blank() -> dict:
    return {"users": {}, "api_keys": {}}


def load_store() -> dict:
    path = store_path()
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            return _blank()
        data.setdefault("users", {})
        data.setdefault("api_keys", {})
        return data
    except FileNotFoundError:
        return _blank()
    except ValueError as e:
        # Corrupt file: quarantine it for forensics instead of silently
        # resetting live identities and keys.
        backup = f"{path}.corrupt-{int(time.time())}"
        try:
            os.replace(path, backup)
        except OSError:
            backup = "(backup failed)"
        print(f"ERROR: auth store corrupt ({e}); moved to {backup}, starting blank.")
        return _blank()


@contextmanager
def _locked():
    """Exclusive inter-process lock around read-modify-write cycles.

    Writes already land via atomic os.replace, so readers need no lock;
    this only serializes writers to prevent lost updates.
    """
    if fcntl is None:
        yield
        return
    os.makedirs(os.path.dirname(store_path()) or ".", exist_ok=True)
    with open(store_path() + ".lock", "w", encoding="utf-8") as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(lock.fileno(), fcntl.LOCK_UN)


def _save_store(data: dict) -> None:
    path = store_path()
    directory = os.path.dirname(path) or "."
    os.makedirs(directory, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=directory, prefix=".auth_store")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def hash_password(password: str, salt: str = None) -> str:
    """Return 'salt$hex' PBKDF2-SHA256 hash for storage."""
    salt = salt or secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), salt.encode("utf-8"), 100_000
    ).hex()
    return f"{salt}${digest}"


def check_password(password: str, stored: str) -> bool:
    """Constant-time comparison of a password against a stored hash."""
    try:
        salt, digest = stored.split("$", 1)
    except ValueError:
        return False
    candidate = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), salt.encode("utf-8"), 100_000
    ).hex()
    return secrets.compare_digest(candidate, digest)


def get_user_by_email(email: str) -> dict | None:
    return load_store()["users"].get(email.lower())


def create_user(email: str, password: str, tier: str = "free") -> dict:
    """Create and persist a user; raises ValueError on duplicates/bad tier."""
    with _locked():
        if tier not in TIERS:
            raise ValueError(f"Unknown tier: {tier}")
        data = load_store()
        key = email.lower()
        if key in data["users"]:
            raise ValueError("Account already exists")
        user_id = f"user_{key.split('@')[0]}"
        data["users"][key] = {
            "user_id": user_id,
            "email": email,
            "tier": tier,
            "password_hash": hash_password(password),
        }
        _save_store(data)
        return data["users"][key]


def verify_user(email: str, password: str) -> dict | None:
    """Return the user record when credentials match, else None."""
    user = get_user_by_email(email)
    if user and check_password(password, user.get("password_hash", "")):
        return user
    return None


def set_user_tier(email: str, tier: str) -> dict:
    """Persist a tier change for a user; raises ValueError when unknown."""
    with _locked():
        if tier not in TIERS:
            raise ValueError(f"Unknown tier: {tier}")
        data = load_store()
        key = email.lower()
        if key not in data["users"]:
            raise ValueError("Account not found")
        data["users"][key]["tier"] = tier
        _save_store(data)
        return data["users"][key]


def save_api_key(record: dict) -> None:
    """Persist an API key record under its SHA-256 lookup hash.

    The plaintext key itself is never written to disk.
    """
    with _locked():
        data = load_store()
        lookup = hashlib.sha256(record["api_key"].encode("utf-8")).hexdigest()
        data["api_keys"][lookup] = {
            "key_id": record["key_id"],
            "user_id": record["user_id"],
            "tier": record["tier"],
            "rate_limit": record["rate_limit"],
            "created_at": record["created_at"],
            "last_used": record.get("last_used"),
        }
        _save_store(data)


def get_api_key(api_key: str) -> dict | None:
    """Look up a key record by hashing the presented key."""
    lookup = hashlib.sha256(api_key.encode("utf-8")).hexdigest()
    record = load_store()["api_keys"].get(lookup)
    if record is None:
        return None
    return {**record, "_lookup": lookup}


def touch_api_key(api_key: str, timestamp: str) -> None:
    with _locked():
        data = load_store()
        lookup = hashlib.sha256(api_key.encode("utf-8")).hexdigest()
        if lookup in data["api_keys"]:
            data["api_keys"][lookup]["last_used"] = timestamp
            _save_store(data)


def find_api_key_by_id(key_id: str) -> dict | None:
    """Find the first record whose key_id contains key_id (for revocation)."""
    for lookup, record in load_store()["api_keys"].items():
        if key_id in record.get("key_id", ""):
            return {**record, "_lookup": lookup}
    return None


def delete_api_key_by_lookup(lookup: str) -> bool:
    """Remove a key by its store lookup; True when one was removed."""
    with _locked():
        data = load_store()
        if lookup in data["api_keys"]:
            del data["api_keys"][lookup]
            _save_store(data)
            return True
        return False


def delete_api_key_by_id(key_id: str) -> bool:
    """Remove the first key containing key_id; True when one was removed."""
    found = find_api_key_by_id(key_id)
    if found is None:
        return False
    return delete_api_key_by_lookup(found["_lookup"])


def list_api_keys() -> list:
    """Return key_id prefixes (never secrets)."""
    return [r.get("key_id") for r in load_store()["api_keys"].values()]
