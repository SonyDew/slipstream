"""Password hashing, session tokens and CSRF helpers.

Argon2id is the primary hasher (memory-hard, current OWASP recommendation).
bcrypt verification is retained so hashes created by an older deployment keep
working and are transparently upgraded on the next successful login.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
from dataclasses import dataclass

import bcrypt
from argon2 import PasswordHasher
from argon2.exceptions import HashingError, InvalidHashError, VerificationError, VerifyMismatchError
from argon2.low_level import Type

# Tuned for a low-resource VPS (Oracle Ampere / 1 GB class): ~64 MiB, 3 passes.
# Expensive for an attacker, yet a login on a shared ARM core stays well under
# a few hundred milliseconds.
_hasher = PasswordHasher(
    time_cost=3,
    memory_cost=64 * 1024,
    parallelism=2,
    hash_len=32,
    salt_len=16,
    type=Type.ID,
)

MIN_PASSWORD_LENGTH = 10
MAX_PASSWORD_LENGTH = 256  # bound the work an attacker can force us to do

_COMMON_PASSWORDS = frozenset(
    {
        "password123",
        "password1234",
        "qwerty123456",
        "administrator",
        "letmein12345",
        "iloveyou1234",
        "welcome12345",
        "changeme1234",
    }
)


@dataclass(frozen=True)
class PasswordCheck:
    ok: bool
    reason: str = ""


def hash_password(password: str) -> str:
    """Return an Argon2id PHC-format hash. Never logs or echoes the input."""
    if not password:
        raise ValueError("password must not be empty")
    if len(password) > MAX_PASSWORD_LENGTH:
        raise ValueError("password too long")
    try:
        return _hasher.hash(password)
    except HashingError as exc:  # pragma: no cover - argon2 internal failure
        raise RuntimeError("password hashing failed") from exc


def verify_password(password: str, stored_hash: str) -> tuple[bool, bool]:
    """Verify a password.

    Returns ``(is_valid, needs_rehash)``. ``needs_rehash`` is True when the
    stored hash uses bcrypt or outdated Argon2 parameters, so callers can
    transparently upgrade it after a successful login.
    """
    if not password or not stored_hash:
        return False, False

    if stored_hash.startswith("$argon2"):
        try:
            _hasher.verify(stored_hash, password)
        except (VerifyMismatchError, VerificationError, InvalidHashError, ValueError):
            return False, False
        try:
            return True, _hasher.check_needs_rehash(stored_hash)
        except InvalidHashError:  # pragma: no cover
            return True, True

    if stored_hash.startswith(("$2a$", "$2b$", "$2y$")):
        try:
            # bcrypt silently truncates at 72 bytes; do it explicitly.
            ok = bcrypt.checkpw(password.encode("utf-8")[:72], stored_hash.encode("utf-8"))
        except ValueError:
            return False, False
        # Legacy hash: upgrade to Argon2id on success.
        return ok, ok

    return False, False


def validate_password_strength(password: str, *, username: str = "") -> PasswordCheck:
    """Pragmatic strength policy: length first, then basic composition."""
    if len(password) < MIN_PASSWORD_LENGTH:
        return PasswordCheck(False, f"Password must be at least {MIN_PASSWORD_LENGTH} characters.")
    if len(password) > MAX_PASSWORD_LENGTH:
        return PasswordCheck(False, "Password must be at most 256 characters.")
    if username and len(username) >= 3 and username.lower() in password.lower():
        return PasswordCheck(False, "Password must not contain your username.")

    classes = sum(
        [
            any(c.islower() for c in password),
            any(c.isupper() for c in password),
            any(c.isdigit() for c in password),
            any(not c.isalnum() for c in password),
        ]
    )
    if classes < 3:
        return PasswordCheck(
            False,
            "Use at least three of: lowercase letters, uppercase letters, digits, symbols.",
        )
    if password.lower() in _COMMON_PASSWORDS:
        return PasswordCheck(False, "That password is too common.")
    return PasswordCheck(True)


# --------------------------------------------------------------------------- #
# Opaque tokens
# --------------------------------------------------------------------------- #
def generate_token(nbytes: int = 32) -> str:
    """Cryptographically secure, URL-safe opaque token."""
    return secrets.token_urlsafe(nbytes)


def hash_token(token: str) -> str:
    """Hash a session token for at-rest storage.

    Session tokens are high-entropy random values, so a single SHA-256 pass is
    sufficient — unlike a human password there is no brute-force surface — and
    it keeps per-request lookups fast.
    """
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def constant_time_compare(a: str, b: str) -> bool:
    return hmac.compare_digest(a.encode("utf-8"), b.encode("utf-8"))
