"""
AutoShorts Backend — Email Service (Resend).
"""

from __future__ import annotations

from backend.config import FROM_EMAIL, FRONTEND_URL, RESEND_API_KEY


def send_reset_email(to_email: str, name: str, token: str) -> None:
    """Send a password reset email via Resend."""
    if not RESEND_API_KEY:
        # Log the reset URL for development testing
        import logging
        reset_url = f"{FRONTEND_URL}/reset-password?token={token}"
        logging.getLogger("autoshorts.email").info(
            "DEV MODE — password reset URL: %s", reset_url
        )
        return

    import resend
    resend.api_key = RESEND_API_KEY

    reset_url = f"{FRONTEND_URL}/reset-password?token={token}"

    resend.Emails.send({
        "from":    FROM_EMAIL,
        "to":      [to_email],
        "subject": "Reset your AutoShorts password",
        "html":    f"""
        <div style="font-family:sans-serif;max-width:500px;margin:0 auto;">
            <h2>Password Reset</h2>
            <p>Hi {name},</p>
            <p>Click the button below to reset your password. This link expires in 1 hour.</p>
            <a href="{reset_url}"
               style="background:#6366f1;color:white;padding:12px 24px;
                      border-radius:8px;text-decoration:none;display:inline-block;margin:16px 0;">
                Reset Password
            </a>
            <p>If you didn't request this, ignore this email.</p>
        </div>
        """,
    })
