"""
AutoShorts Backend — Auth Router.

Endpoints:
  POST /api/auth/register
  POST /api/auth/login
  GET  /api/auth/me
  PUT  /api/auth/me
  POST /api/auth/change-password
  POST /api/auth/forgot-password
  POST /api/auth/reset-password
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from backend.auth_service import (
    create_access_token,
    generate_reset_token,
    get_current_user,
    hash_password,
    verify_password,
)
from backend.database import get_db
from backend.models import User, UserSchedule
from backend.schemas import (
    ChangePasswordRequest,
    ForgotPasswordRequest,
    LoginRequest,
    RegisterRequest,
    ResetPasswordRequest,
    TokenResponse,
    UpdateSettingsRequest,
    UserResponse,
)

router = APIRouter(prefix="/api/auth", tags=["auth"])


# ── Register ──────────────────────────────────────────────────

@router.post("/register", response_model=TokenResponse, status_code=status.HTTP_201_CREATED)
def register(body: RegisterRequest, db: Session = Depends(get_db)):
    """Create a new user account."""
    existing = db.query(User).filter(User.email == body.email.lower()).first()
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="An account with this email already exists",
        )

    user = User(
        email         = body.email.lower().strip(),
        name          = body.name.strip(),
        password_hash = hash_password(body.password),
        is_active     = True,
        is_verified   = False,
    )
    db.add(user)
    db.flush()  # get the ID before commit

    # Create default schedule for new user
    schedule = UserSchedule(
        user_id        = user.id,
        videos_per_day = 3,
        time_slot_1    = "09:00",
        time_slot_2    = "15:00",
        time_slot_3    = "21:00",
        timezone       = "UTC",
        is_active      = True,
    )
    db.add(schedule)
    db.commit()
    db.refresh(user)

    token = create_access_token(user.id)
    return TokenResponse(
        access_token = token,
        user         = UserResponse.model_validate(user),
    )


# ── Login ─────────────────────────────────────────────────────

@router.post("/login", response_model=TokenResponse)
def login(body: LoginRequest, db: Session = Depends(get_db)):
    """Authenticate and return a JWT access token."""
    user = db.query(User).filter(User.email == body.email.lower()).first()

    if not user or not verify_password(body.password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
        )

    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Account has been deactivated",
        )

    token = create_access_token(user.id)
    return TokenResponse(
        access_token = token,
        user         = UserResponse.model_validate(user),
    )


# ── Get current user ──────────────────────────────────────────

@router.get("/me", response_model=UserResponse)
def get_me(current_user: User = Depends(get_current_user)):
    return current_user


# ── Update settings ───────────────────────────────────────────

@router.put("/me", response_model=UserResponse)
def update_me(
    body:         UpdateSettingsRequest,
    db:           Session = Depends(get_db),
    current_user: User    = Depends(get_current_user),
):
    """Update user profile and content preferences."""
    if body.name            is not None: current_user.name             = body.name.strip()
    if body.channel_niche   is not None: current_user.channel_niche    = body.channel_niche
    if body.default_language is not None: current_user.default_language = body.default_language
    if body.default_gender  is not None: current_user.default_gender   = body.default_gender
    if body.default_privacy is not None: current_user.default_privacy  = body.default_privacy
    if body.videos_per_day  is not None: current_user.videos_per_day   = body.videos_per_day

    db.commit()
    db.refresh(current_user)
    return current_user


# ── Change password ───────────────────────────────────────────

@router.post("/change-password")
def change_password(
    body:         ChangePasswordRequest,
    db:           Session = Depends(get_db),
    current_user: User    = Depends(get_current_user),
):
    if not verify_password(body.current_password, current_user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Current password is incorrect",
        )

    current_user.password_hash = hash_password(body.new_password)
    db.commit()
    return {"message": "Password updated successfully"}


# ── Forgot password ───────────────────────────────────────────

@router.post("/forgot-password")
def forgot_password(body: ForgotPasswordRequest, db: Session = Depends(get_db)):
    """Send a password reset email (if account exists)."""
    user = db.query(User).filter(User.email == body.email.lower()).first()

    # Always return 200 to prevent email enumeration attacks
    if not user:
        return {"message": "If an account exists, a reset email has been sent"}

    token   = generate_reset_token()
    expires = datetime.now(timezone.utc) + timedelta(hours=1)

    user.reset_token         = token
    user.reset_token_expires = expires
    db.commit()

    # Send email (non-blocking — if email fails, reset token is still saved)
    try:
        from backend.email_service import send_reset_email
        send_reset_email(user.email, user.name, token)
    except Exception:
        pass  # Email is optional — user can still reset via the token

    return {"message": "If an account exists, a reset email has been sent"}


# ── Reset password ────────────────────────────────────────────

@router.post("/reset-password")
def reset_password(body: ResetPasswordRequest, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.reset_token == body.token).first()

    if not user:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid or expired reset link",
        )

    if user.reset_token_expires and user.reset_token_expires < datetime.now(timezone.utc):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Reset link has expired. Please request a new one.",
        )

    user.password_hash       = hash_password(body.new_password)
    user.reset_token         = None
    user.reset_token_expires = None
    db.commit()

    return {"message": "Password reset successfully. You can now log in."}
