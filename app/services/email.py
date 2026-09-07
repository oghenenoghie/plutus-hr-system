import base64

import httpx

from app.core.config import get_settings


def send_email_with_attachment(
    *, to: str, subject: str, html_body: str, attachment_bytes: bytes, attachment_filename: str
) -> str:
    """Sends via Resend's HTTP API and returns the provider message id.
    Raises RuntimeError if RESEND_API_KEY isn't configured (dev/test — the
    caller is expected to record this as a failed delivery, not crash) or
    if the request itself fails.
    """
    settings = get_settings()
    if not settings.resend_api_key:
        raise RuntimeError("email delivery is not configured (RESEND_API_KEY unset)")

    response = httpx.post(
        "https://api.resend.com/emails",
        headers={"Authorization": f"Bearer {settings.resend_api_key}"},
        json={
            "from": settings.email_from,
            "to": [to],
            "subject": subject,
            "html": html_body,
            "attachments": [
                {
                    "filename": attachment_filename,
                    "content": base64.b64encode(attachment_bytes).decode("ascii"),
                }
            ],
        },
        timeout=10.0,
    )
    response.raise_for_status()
    message_id: str = response.json()["id"]
    return message_id
