"""Small dependency-free event ledger for the BIPU newsletter funnel."""
from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any

ALLOWED_EVENTS = {
    "legacy_recipient_eligible",
    "repermission_sent",
    "repermission_delivered",
    "repermission_opened",
    "optin_page_viewed",
    "bipu_opt_in_completed",
    "book_delivery_issued",
    "book_download_started",
    "book_download_completed",
    "onboarding_email_sent",
    "onboarding_email_opened",
    "onboarding_reply_received",
    "marvin_session_started",
    "bipu_entry_interest_submitted",
    "bipu_entry_purchase_completed",
    "research_interest_submitted",
    "free_call_booked",
    "paid_audit_inquiry_submitted",
    "unsubscribe_recorded",
    "complaint_recorded",
    "hard_bounce_recorded",
    "email.sent",
    "email.delivered",
    "email.opened",
    "email.clicked",
    "email.bounced",
    "email.complained",
    "email.failed",
    "email.delivery_delayed",
}

@dataclass(frozen=True)
class Event:
    event_id: str
    event_name: str
    occurred_at: str
    campaign_id: str
    batch_id: str | None = None
    variant: str | None = None
    source_list: str | None = None
    cohort: str | None = None
    subscriber_id: str | None = None
    consent_scope: str | None = None
    provider_event_id: str | None = None
    provider_email_id: str | None = None

    def as_db_tuple(self) -> tuple[Any, ...]:
        return (
            self.event_id, self.event_name, self.occurred_at, self.campaign_id,
            self.batch_id, self.variant, self.source_list, self.cohort,
            self.subscriber_id, self.consent_scope, self.provider_event_id,
            self.provider_email_id,
        )


def connect(path: str | Path) -> sqlite3.Connection:
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("""CREATE TABLE IF NOT EXISTS events (
        event_id TEXT PRIMARY KEY,
        event_name TEXT NOT NULL,
        occurred_at TEXT NOT NULL,
        campaign_id TEXT NOT NULL,
        batch_id TEXT,
        variant TEXT,
        source_list TEXT,
        cohort TEXT,
        subscriber_id TEXT,
        consent_scope TEXT,
        provider_event_id TEXT UNIQUE,
        provider_email_id TEXT
    )""")
    conn.execute("CREATE INDEX IF NOT EXISTS events_funnel_idx ON events(campaign_id, event_name, source_list, cohort, variant)")
    return conn


def validate_event(event: Event) -> None:
    if event.event_name not in ALLOWED_EVENTS:
        raise ValueError(f"unknown event: {event.event_name}")
    if event.event_name == "bipu_opt_in_completed" and event.consent_scope != "bipu_newsletter":
        raise ValueError("BIPU opt-in requires consent_scope=bipu_newsletter")
    if event.event_name in {"book_delivery_issued", "book_download_started", "book_download_completed"} and not event.subscriber_id:
        raise ValueError("book events require subscriber_id")


def record(conn: sqlite3.Connection, event: Event) -> bool:
    validate_event(event)
    before = conn.total_changes
    conn.execute("""INSERT OR IGNORE INTO events VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""", event.as_db_tuple())
    conn.commit()
    return conn.total_changes > before


def metrics(conn: sqlite3.Connection, campaign_id: str) -> dict[str, Any]:
    rows = conn.execute("SELECT event_name, COUNT(*) AS n FROM events WHERE campaign_id=? GROUP BY event_name", (campaign_id,)).fetchall()
    counts = {row["event_name"]: row["n"] for row in rows}
    def ratio(numerator: str, denominator: str) -> dict[str, Any]:
        n, d = counts.get(numerator, 0), counts.get(denominator, 0)
        return {"numerator": n, "denominator": d, "rate": (n / d if d else None)}
    downstream_numerator = sum(counts.get(name, 0) for name in {
        "bipu_entry_interest_submitted", "bipu_entry_purchase_completed",
        "research_interest_submitted", "free_call_booked", "paid_audit_inquiry_submitted",
    })
    downstream_denominator = counts.get("bipu_opt_in_completed", 0)
    return {
        "campaign_id": campaign_id,
        "counts": counts,
        "rates": {
            "opened_per_delivered": ratio("repermission_opened", "repermission_delivered"),
            "optin_per_delivered": ratio("bipu_opt_in_completed", "repermission_delivered"),
            "book_download_per_optin": ratio("book_download_completed", "bipu_opt_in_completed"),
            "onboarding_reply_per_optin": ratio("onboarding_reply_received", "bipu_opt_in_completed"),
            "downstream_action_per_optin": {
                "numerator": downstream_numerator,
                "denominator": downstream_denominator,
                "rate": (downstream_numerator / downstream_denominator if downstream_denominator else None),
            },
        },
    }

def main() -> None:
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("db")
    parser.add_argument("campaign_id")
    args = parser.parse_args()
    print(json.dumps(metrics(connect(args.db), args.campaign_id), indent=2))

if __name__ == "__main__":
    main()
