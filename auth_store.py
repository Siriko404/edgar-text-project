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


PBKDF2_PREFIX = "pbkdf2_sha256"
PBKDF2_ITERATIONS = 600_000  # OWASP guidance for PBKDF2-HMAC-SHA256
LEGACY_ITERATIONS = 100_000  # hashes written before the prefix existed: 'salt$hex'


def _pbkdf2(password: str, salt: str, iterations: int) -> str:
    return hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), salt.encode("utf-8"), iterations
    ).hex()


def hash_password(password: str, salt: str = None) -> str:
    """Return 'pbkdf2_sha256$iterations$salt$hex' for storage."""
    salt = salt or secrets.token_hex(16)
    digest = _pbkdf2(password, salt, PBKDF2_ITERATIONS)
    return f"{PBKDF2_PREFIX}${PBKDF2_ITERATIONS}${salt}${digest}"


def check_password(password: str, stored: str) -> bool:
    """Constant-time comparison of a password against a stored hash.

    Reads both the current format and the older 'salt$hex' one (100k rounds).
    """
    parts = stored.split("$")
    try:
        if parts[0] == PBKDF2_PREFIX and len(parts) == 4:
            iterations, salt, digest = int(parts[1]), parts[2], parts[3]
            if not 1 <= iterations <= 5_000_000:
                return False
        elif len(parts) == 2:
            iterations, (salt, digest) = LEGACY_ITERATIONS, parts
        else:
            return False
    except ValueError:
        return False
    return secrets.compare_digest(_pbkdf2(password, salt, iterations), digest)


# Checked when the email is unknown, so a login takes as long either way.
_DUMMY_HASH = hash_password("not-a-real-password")


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
        # The whole address goes into the id: 'alice@a.com' and 'alice@b.com' are different people.
        suffix = hashlib.sha256(key.encode("utf-8")).hexdigest()[:8]
        user_id = f"user_{key.split('@')[0]}_{suffix}"
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
    if user is None:
        check_password(password, _DUMMY_HASH)
        return None
    if check_password(password, user.get("password_hash", "")):
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


MIN_KEY_ID_LENGTH = 8


def find_api_key_by_id(key_id: str, user_id: str | None = None) -> dict | None:
    """Find a key whose key_id starts with key_id (for revocation).

    With user_id, only that user's keys are searched, so one account cannot
    match another's. Callers that take the id from a request should enforce
    MIN_KEY_ID_LENGTH first.
    """
    for lookup, record in load_store()["api_keys"].items():
        if user_id is not None and record.get("user_id") != user_id:
            continue
        if record.get("key_id", "").startswith(key_id):
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


def delete_api_key_by_id(key_id: str, user_id: str | None = None) -> bool:
    """Remove the first key starting with key_id; True when one was removed."""
    found = find_api_key_by_id(key_id, user_id)
    if found is None:
        return False
    return delete_api_key_by_lookup(found["_lookup"])


def list_api_keys() -> list:
    """Return key_id prefixes (never secrets)."""
    return [r.get("key_id") for r in load_store()["api_keys"].values()]
