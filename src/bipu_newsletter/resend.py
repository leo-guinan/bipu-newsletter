"""Resend transport adapter.

This module sends only when RESEND_API_KEY and GUIDE_EMAIL_FROM are present.
It returns the provider message ID and never treats a local HTTP request as
proof of delivery; delivery is reconciled through the webhook ledger.
"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request


def send_text(*, recipient: str, subject: str, text: str, tags: dict[str, str] | None = None) -> str:
    api_key = os.environ.get("RESEND_API_KEY", "").strip()
    sender = os.environ.get("GUIDE_EMAIL_FROM", "").strip()
    if not api_key or not sender:
        raise RuntimeError("email_transport_not_configured")
    payload = {"from": sender, "to": [recipient], "subject": subject, "text": text}
    reply_to = os.environ.get("GUIDE_EMAIL_REPLY_TO", "").strip()
    if reply_to:
        payload["reply_to"] = [reply_to]
    if tags:
        payload["tags"] = [{"name": key, "value": value} for key, value in tags.items()]
    request = urllib.request.Request(
        "https://api.resend.com/emails",
        data=json.dumps(payload).encode(),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "User-Agent": "bipu-newsletter/0.1",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            body = json.loads(response.read().decode() or "{}")
    except urllib.error.HTTPError as exc:
        # Do not return the provider body: it may contain recipient/account details.
        raise RuntimeError(f"resend_http_{exc.code}") from exc
    message_id = body.get("id")
    if not message_id:
        raise RuntimeError("resend_missing_message_id")
    return str(message_id)
