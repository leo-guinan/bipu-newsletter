"""Metrics and authenticated Resend webhook receiver."""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from .ledger import Event, connect, metrics, record

DB = Path(os.environ.get("NEWSLETTER_DATA_DIR", "./var")) / "newsletter.sqlite3"
CAMPAIGN = os.environ.get("NEWSLETTER_CAMPAIGN_ID", "bipu-repermission-v0.2")


def parse_provider_event(payload: dict, provider_event_id: str | None = None) -> Event:
    data = payload.get("data") or {}
    tags = data.get("tags") or {}
    provider_key = provider_event_id or f"fallback:{data.get('email_id') or payload.get('created_at')}:{payload.get('type')}"
    return Event(
        event_id=f"provider:{provider_key}",
        event_name=str(payload.get("type") or ""),
        occurred_at=str(payload.get("created_at") or ""),
        campaign_id=tags.get("campaign", CAMPAIGN),
        batch_id=tags.get("batch"),
        variant=tags.get("variant"),
        source_list=tags.get("source_list"),
        cohort=tags.get("cohort"),
        provider_email_id=data.get("email_id"),
    )


def verify_svix_signature(*, body: bytes, headers: dict[str, str], secret: str, tolerance_seconds: int = 300) -> bool:
    """Verify a Resend/Svix webhook using the raw request body."""
    if not secret.startswith("whsec_"):
        return False
    msg_id = headers.get("svix-id", "")
    timestamp = headers.get("svix-timestamp", "")
    signatures = headers.get("svix-signature", "").split()
    if not msg_id or not timestamp or not signatures:
        return False
    try:
        ts = int(timestamp)
        if abs(time.time() - ts) > tolerance_seconds:
            return False
        key = base64.b64decode(secret[6:] + "===")
        signed = f"{msg_id}.{timestamp}.".encode() + body
        expected = base64.b64encode(hmac.new(key, signed, hashlib.sha256).digest()).decode()
    except (ValueError, TypeError):
        return False
    return any(hmac.compare_digest(item.removeprefix("v1,"), expected) for item in signatures)


class Handler(BaseHTTPRequestHandler):
    def send_json(self, status: int, body: dict) -> None:
        raw = json.dumps(body).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self) -> None:
        if self.path == "/healthz":
            self.send_json(200, {"ok": True, "campaign_id": CAMPAIGN})
            return
        if self.path == "/metrics":
            self.send_json(200, metrics(connect(DB), CAMPAIGN))
            return
        self.send_json(404, {"error": "not_found"})

    def do_POST(self) -> None:
        if self.path != "/webhooks/resend":
            self.send_json(404, {"error": "not_found"})
            return
        length = int(self.headers.get("Content-Length", "0"))
        body = self.rfile.read(length)
        headers = {key.lower(): value for key, value in self.headers.items()}
        if not verify_svix_signature(
            body=body,
            headers=headers,
            secret=os.environ.get("RESEND_WEBHOOK_SECRET", ""),
        ):
            self.send_json(401, {"error": "invalid_webhook_signature"})
            return
        try:
            event = parse_provider_event(json.loads(body.decode()), headers["svix-id"])
            inserted = record(connect(DB), event)
        except (ValueError, json.JSONDecodeError):
            self.send_json(400, {"error": "invalid_webhook_payload"})
            return
        self.send_json(200, {"ok": True, "inserted": inserted})

    def log_message(self, format: str, *args: object) -> None:
        return


def main() -> None:
    DB.parent.mkdir(parents=True, exist_ok=True)
    server = ThreadingHTTPServer(
        (os.environ.get("NEWSLETTER_HOST", "127.0.0.1"), int(os.environ.get("NEWSLETTER_PORT", "4317"))),
        Handler,
    )
    server.serve_forever()


if __name__ == "__main__":
    main()
