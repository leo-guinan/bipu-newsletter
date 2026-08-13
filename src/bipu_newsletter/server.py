"""Metrics and authenticated Resend webhook receiver."""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import time
import re
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from .ledger import Event, connect, create_consent_and_entitlement, entitlement_for_token, mark_download, metrics, record

DB = Path(os.environ.get("NEWSLETTER_DATA_DIR", "./var")) / "newsletter.sqlite3"
CAMPAIGN = os.environ.get("NEWSLETTER_CAMPAIGN_ID", "bipu-repermission-v0.2")
LEAD_MAGNET_CAMPAIGN = "bipu-lead-magnet-v0.1"
BOOK_FILE = Path(os.environ.get("BIPU_BOOK_FILE", "./private/manuscript.epub"))
BOOK_FILES = {
    "epub": BOOK_FILE,
    "pdf": Path(os.environ.get("BIPU_BOOK_PDF_FILE", "./private/manuscript.pdf")),
}
PUBLIC_SITE = Path(os.environ.get("BIPU_PUBLIC_SITE", "./web"))


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
        provider_event_id=provider_event_id,
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
        if self.path in {"/", "/index.html"}:
            self.serve_file(PUBLIC_SITE / "index.html", "text/html; charset=utf-8")
            return
        if self.path == "/healthz":
            self.send_json(200, {"ok": True, "campaign_id": CAMPAIGN})
            return
        if self.path.startswith("/assets/"):
            asset = (PUBLIC_SITE / self.path.removeprefix("/" )).resolve()
            if PUBLIC_SITE.resolve() not in asset.parents:
                self.send_json(404, {"error": "not_found"})
                return
            self.serve_file(asset, "text/css; charset=utf-8")
            return
        if self.path.startswith("/download/"):
            token = self.path.removeprefix("/download/").split("?", 1)[0]
            self.download_book(token)
            return
        if self.path == "/metrics":
            self.send_json(200, metrics(connect(DB), CAMPAIGN))
            return
        self.send_json(404, {"error": "not_found"})

    def serve_file(self, path: Path, content_type: str) -> None:
        try:
            raw = path.read_bytes()
        except OSError:
            self.send_json(404, {"error": "not_found"})
            return
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def download_book(self, token: str) -> None:
        parts = token.split("/", 1)
        if len(parts) != 2 or parts[0] not in BOOK_FILES or not re.fullmatch(r"[A-Za-z0-9_-]{32,64}", parts[1]):
            self.send_json(404, {"error": "not_found"})
            return
        download_format, token = parts
        conn = connect(DB)
        entitlement = entitlement_for_token(conn, token)
        if entitlement is None:
            self.send_json(404, {"error": "entitlement_not_found"})
            return
        try:
            book_file = BOOK_FILES[download_format]
            size = book_file.stat().st_size
            handle = book_file.open("rb")
        except OSError:
            self.send_json(503, {"error": "book_unavailable"})
            return
        mark_download(conn, entitlement, completed=False, occurred_at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), download_format=download_format)
        self.send_response(200)
        self.send_header("Content-Type", "application/epub+zip" if download_format == "epub" else "application/pdf")
        self.send_header("Content-Disposition", f'attachment; filename="the-art-of-time-and-war.{download_format}"')
        self.send_header("Content-Length", str(size))
        self.end_headers()
        try:
            while chunk := handle.read(1024 * 64):
                self.wfile.write(chunk)
            mark_download(conn, entitlement, completed=True, occurred_at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), download_format=download_format)
        finally:
            handle.close()

    def do_POST(self) -> None:
        if self.path == "/api/opt-in":
            self.handle_opt_in()
            return
        self.handle_webhook()

    def handle_opt_in(self) -> None:
        length = int(self.headers.get("Content-Length", "0"))
        if length > 4096:
            self.send_json(413, {"error": "request_too_large"})
            return
        try:
            payload = json.loads(self.rfile.read(length).decode())
            if payload.get("consent") is not True:
                raise ValueError("consent_required")
            result = create_consent_and_entitlement(
                connect(DB), email=str(payload.get("email", "")),
                occurred_at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            )
            token = result.get("token")
            if not token:
                self.send_json(409, {"error": "entitlement_already_issued"})
                return
            self.send_json(201, {"ok": True, "campaign_id": LEAD_MAGNET_CAMPAIGN, "download_urls": {"epub": "/download/epub/" + str(token), "pdf": "/download/pdf/" + str(token)}})
        except ValueError as exc:
            self.send_json(422, {"error": str(exc)})
        except (json.JSONDecodeError, UnicodeDecodeError):
            self.send_json(400, {"error": "invalid_json"})

    def handle_webhook(self) -> None:
        if self.path != "/webhooks/resend":
            self.send_json(404, {"error": "not_found"})
            return
        length = int(self.headers.get("Content-Length", "0"))
        body = self.rfile.read(length)
        headers = {key.lower(): value for key, value in self.headers.items()}
        if not verify_svix_signature(body=body, headers=headers, secret=os.environ.get("RESEND_WEBHOOK_SECRET", "")):
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
