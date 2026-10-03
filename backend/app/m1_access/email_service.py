"""Email delivery service for 2FA / OTP verification.

Supports SSL/TLS SMTP (configured in backend/.env) with a Console fallback.
"""
import logging
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from typing import Optional
from app.m1_access.config import (
    EMAIL_BACKEND,
    SMTP_HOST,
    SMTP_PORT,
    SMTP_USER,
    SMTP_PASSWORD,
    SMTP_FROM,
    SMTP_USE_SSL,
)

logger = logging.getLogger("truepixels.email")


class EmailService:
    @staticmethod
    def send_otp_email(recipient_email: str, otp_code: str, user_name: Optional[str] = None) -> bool:
        """Sends an OTP email for account verification or 2FA login."""
        subject = f"Your TruePixels.rgb Verification Code: {otp_code}"
        display_name = user_name or "TruePixels User"

        text_content = f"""Hello {display_name},

Your verification code for TruePixels.rgb is:

    {otp_code}

This code will expire in 5 minutes. If you did not request this code, please ignore this email.

Best regards,
TruePixels.rgb Security Team
"""
        html_content = f"""<!DOCTYPE html>
<html>
<head>
<style>
  body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; background-color: #f4f4f7; padding: 20px; }}
  .card {{ max-width: 500px; margin: 0 auto; background: #ffffff; padding: 30px; border-radius: 8px; box-shadow: 0 4px 12px rgba(0,0,0,0.08); }}
  .logo {{ font-size: 24px; font-weight: 700; color: #1e293b; margin-bottom: 20px; }}
  .logo span {{ color: #6366f1; }}
  .otp-box {{ background-color: #f1f5f9; padding: 18px; font-size: 32px; font-weight: 800; letter-spacing: 6px; text-align: center; color: #312e81; border-radius: 6px; margin: 25px 0; border: 1px dashed #6366f1; }}
  .footer {{ font-size: 12px; color: #64748b; margin-top: 30px; text-align: center; }}
</style>
</head>
<body>
<div class="card">
  <div class="logo">TruePixels<span>.rgb</span></div>
  <p>Hello <strong>{display_name}</strong>,</p>
  <p>Please use the following 6-digit verification code to complete your sign-in / registration:</p>
  <div class="otp-box">{otp_code}</div>
  <p>This code will expire in <strong>5 minutes</strong>. If you did not request this, you can safely ignore this email.</p>
  <div class="footer">&copy; TruePixels.rgb — AI-Generated Image Detection System</div>
</div>
</body>
</html>"""

        import os
        from app.shared.logging import emit

        clean_recipient = recipient_email.strip().lower()
        smtp_backend = os.getenv("EMAIL_BACKEND", "smtp")
        smtp_host = os.getenv("SMTP_HOST", "smtp.gmail.com")
        smtp_port = int(os.getenv("SMTP_PORT", "587"))
        smtp_user = os.getenv("SMTP_USER", "")
        # INTEGRATION: the default used to be a real Gmail app password. A
        # credential must never live in source control; set SMTP_PASSWORD in
        # .env instead. Without it this falls through to the console path
        # below. See changes.md.
        smtp_password = os.getenv("SMTP_PASSWORD", "").replace("-", "").replace(" ", "").strip()
        smtp_from = os.getenv("SMTP_FROM", "")

        if smtp_backend.lower() == "smtp" and smtp_user and smtp_password:
            try:
                msg = MIMEMultipart("alternative")
                msg["Subject"] = subject
                msg["From"] = f"TruePixels Security <{smtp_from}>"
                msg["To"] = clean_recipient
                msg["Reply-To"] = smtp_from

                part1 = MIMEText(text_content, "plain")
                part2 = MIMEText(html_content, "html")
                msg.attach(part1)
                msg.attach(part2)

                # Connect via TLS on 587
                try:
                    server = smtplib.SMTP(smtp_host, smtp_port, timeout=15)
                    server.starttls()
                    server.login(smtp_user, smtp_password)
                    server.sendmail(smtp_from, [clean_recipient], msg.as_string())
                    server.quit()
                    emit("authentication", f"2FA OTP email delivered via Gmail TLS to {clean_recipient}", severity="info")
                    return True
                except Exception as e_tls:
                    # Fallback to SSL on 465
                    server = smtplib.SMTP_SSL(smtp_host, 465, timeout=15)
                    server.login(smtp_user, smtp_password)
                    server.sendmail(smtp_from, [clean_recipient], msg.as_string())
                    server.quit()
                    emit("authentication", f"2FA OTP email delivered via Gmail SSL to {clean_recipient}", severity="info")
                    return True
            except Exception as e:
                emit("error", f"Gmail SMTP delivery failed to {clean_recipient}: {e}", severity="error")

        # Fallback to Console / Development mode.
        # INTEGRATION (changes.md 6.10): the code goes to the developer's
        # console ONLY (stdout logger, never persisted). It used to go through
        # emit(), which also writes D6 - so every console-mode OTP was readable
        # by admins in the log viewer. D6 records only that a code was issued.
        from app.shared.logging import logger as console_only

        console_only.info(f"2FA OTP simulated in console for {clean_recipient}: code={otp_code} "
                          "[development console only - not stored]")
        emit("authentication", f"2FA OTP issued (console delivery, code not logged) for {clean_recipient}",
             severity="info")
        return True
