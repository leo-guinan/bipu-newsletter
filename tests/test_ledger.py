import base64
import hashlib
import hmac
import time

import pytest

from bipu_newsletter.ledger import Event, connect, create_consent_and_entitlement, entitlement_for_token, mark_download, metrics, record
from bipu_newsletter.server import verify_svix_signature


def event(name, event_id, **kwargs):
    return Event(event_id, name, "2026-08-13T00:00:00Z", "campaign-1", **kwargs)


def test_optin_requires_explicit_scope():
    conn = connect(":memory:")
    with pytest.raises(ValueError):
        record(conn, event("bipu_opt_in_completed", "e1", subscriber_id="s1"))


def test_provider_events_are_idempotent():
    conn = connect(":memory:")
    item = event("email.delivered", "e1", provider_event_id="svix-1", provider_email_id="mail-1")
    assert record(conn, item) is True
    assert record(conn, item) is False
    assert conn.execute("SELECT COUNT(*) FROM events").fetchone()[0] == 1


def test_funnel_metrics_keep_denominators():
    conn = connect(":memory:")
    record(conn, event("repermission_delivered", "e1"))
    record(conn, event("repermission_opened", "e2"))
    record(conn, event("bipu_opt_in_completed", "e3", subscriber_id="s1", consent_scope="bipu_newsletter"))
    record(conn, event("book_download_completed", "e4", subscriber_id="s1"))
    result = metrics(conn, "campaign-1")
    assert result["rates"]["opened_per_delivered"] == {"numerator": 1, "denominator": 1, "rate": 1.0}
    assert result["rates"]["optin_per_delivered"]["denominator"] == 1
    assert result["rates"]["book_download_per_optin"]["rate"] == 1.0


def test_provider_event_id_is_preserved():
    payload = {"type": "email.delivered", "created_at": "2026-08-13T00:00:00Z", "data": {"email_id": "mail-1"}}
    from bipu_newsletter.server import parse_provider_event
    assert parse_provider_event(payload, "svix-1").provider_event_id == "svix-1"


def test_svix_signature_verification():
    body = b'{"type":"email.delivered"}'
    secret = "whsec_" + base64.b64encode(b"test-secret").decode()
    message_id = "msg-1"
    timestamp = str(int(time.time()))
    signed = f"{message_id}.{timestamp}.".encode() + body
    digest = base64.b64encode(hmac.new(b"test-secret", signed, hashlib.sha256).digest()).decode()
    headers = {"svix-id": message_id, "svix-timestamp": timestamp, "svix-signature": f"v1,{digest}"}
    assert verify_svix_signature(body=body, headers=headers, secret=secret)
    assert not verify_svix_signature(body=b"tampered", headers=headers, secret=secret)


def test_book_entitlement_requires_consent_and_tracks_download():
    conn = connect(":memory:")
    result = create_consent_and_entitlement(conn, email=" Reader@Example.com ", occurred_at="2026-08-13T00:00:00Z")
    assert result["created"] is True
    row = entitlement_for_token(conn, str(result["token"]))
    assert row is not None
    mark_download(conn, row, completed=False, occurred_at="2026-08-13T00:01:00Z", download_format="epub")
    mark_download(conn, row, completed=True, occurred_at="2026-08-13T00:02:00Z", download_format="epub")
    result = metrics(conn, "bipu-lead-magnet-v0.1")
    assert result["counts"]["bipu_opt_in_completed"] == 1
    assert result["counts"]["book_download_completed"] == 1
