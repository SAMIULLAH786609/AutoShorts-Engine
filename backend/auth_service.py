"""
AutoShorts Backend — Auth Service.

Handles:
  - Password hashing / verification (bcrypt)
  - JWT token creation / verification
  - OAuth token encryption / decryption (Fernet)
  - Current user dependency for FastAPI routes
"""

from __future__ import annotations

import secrets
from datetime import datetime, timedelta, timezone
from typing import Optional

from cryptography.fernet import Fernet, InvalidToken
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt
from passlib.context import CryptContext
from sqlalchemy.orm import Session

from backend.config import (
    ACCESS_TOKEN_EXPIRE_MINUTES,
    ALGORITHM,
    FERNET_KEY,
    SECRET_KEY,
)
from backend.database import get_db
from backend.models import User

# ── Password hashing ──────────────────────────────────────────
_pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def hash_password(plain: str) -> str:
    return _pwd_context.hash(plain)


def verify_password(plain: str, hashed: str) -> bool:
    return _pwd_context.verify(plain, hashed)


# ── JWT tokens ────────────────────────────────────────────────

def create_access_token(user_id: str, expires_minutes: int = ACCESS_TOKEN_EXPIRE_MINUTES) -> str:
    expire = datetime.now(timezone.utc) + timedelta(minutes=expires_minutes)
    payload = {"sub": user_id, "exp": expire}
    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)


def decode_access_token(token: str) -> str | None:
    """Return user_id from token, or None if invalid/expired."""
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        return payload.get("sub")
    except JWTError:
        return None


# ── Fernet encryption for OAuth tokens ────────────────────────

def _fernet() -> Fernet | None:
    if not FERNET_KEY:
        return None
    try:
        key = FERNET_KEY.encode() if isinstance(FERNET_KEY, str) else FERNET_KEY
        # Fernet keys must be 32 url-safe base64 bytes — generate if needed
        return Fernet(key)
    except Exception:
        return None


def encrypt_token(plain_text: str) -> str:
    """Encrypt an OAuth token for database storage."""
    f = _fernet()
    if f is None:
        # Fall back to plain storage if no Fernet key configured
        return plain_text
    return f.encrypt(plain_text.encode()).decode()


def decrypt_token(cipher_text: str) -> str:
    """Decrypt an OAuth token retrieved from the database."""
    f = _fernet()
    if f is None:
        return cipher_text
    try:
        return f.decrypt(cipher_text.encode()).decode()
    except InvalidToken:
        return cipher_text


# ── Password reset tokens ─────────────────────────────────────

def generate_reset_token() -> str:
    return secrets.token_urlsafe(32)


# ── FastAPI dependency — current authenticated user ────────────

_bearer = HTTPBearer(auto_error=False)


def get_current_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(_bearer),
    db: Session = Depends(get_db),
) -> User:
    """Dependency that returns the authenticated User or raises 401."""
    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
        )

    user_id = decode_access_token(credentials.credentials)

    if not user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
        )

    user = db.query(User).filter(User.id == user_id, User.is_active == True).first()

    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found or deactivated",
        )

    return user
