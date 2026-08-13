# BIPU Newsletter Infrastructure

Open-source reference implementation for a small, self-hostable newsletter funnel using Resend as an email transport and a local SQLite event ledger.

The goal is not to recreate a big-tech attention platform in a smaller trench coat. It is to keep the campaign state, consent record, funnel events, and outcome measurements under the operator's control.

## Scope

This repository covers:

- campaign and cohort identifiers;
- a private runtime data directory;
- idempotent event storage;
- Resend message IDs and webhook event ingestion;
- funnel aggregation from delivery to opt-in and book download;
- downstream BIPU interest events;
- health and metrics endpoints;
- a systemd deployment shape.

It deliberately does not contain:

- subscriber exports;
- email addresses;
- names or raw replies;
- API keys or webhook secrets;
- a book file;
- live campaign receipts;
- a claim that a send or signup happened.

## State model

```text
legacy source list
  -> repermission send
  -> Resend delivery/open/click events
  -> first-party BIPU opt-in
  -> book entitlement and download
  -> onboarding
  -> entry/research/service interest
```

An open is not consent. A click is not consent. A download is not consent. Only the first-party opt-in event creates BIPU subscription state.

## Runtime boundaries

- Resend is transport and provider event source.
- This service is the campaign ledger and metrics projection.
- The first-party opt-in surface owns consent capture.
- Book delivery is gated by a recorded opt-in.
- Raw addresses remain in the private runtime database and are never returned by public metrics.
- Webhook deliveries are at-least-once; `svix-id` is the idempotency key.
- Event order is not assumed. Aggregation uses event timestamps and observed state.

## Local development

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -e '.[test]'
pytest -q
python -m bipu_newsletter.server
```

The service defaults to `127.0.0.1:4317` and `./var/newsletter.sqlite3`.

## Configuration

Copy `.env.example` to a private runtime environment. Never commit the copy.

Required before production:

- `RESEND_API_KEY`
- `GUIDE_EMAIL_FROM` — an address on the verified domain
- `GUIDE_EMAIL_REPLY_TO`
- `RESEND_WEBHOOK_SECRET` — registered through Resend's webhook configuration
- `NEWSLETTER_DATA_DIR`
- `NEWSLETTER_PUBLIC_BASE_URL`

The send adapter is intentionally isolated. It records provider message IDs and does not mark a message sent when transport is missing or rejected.

## Resend event boundary

Configure Resend to send these events to the production HTTPS webhook:

- `email.sent`
- `email.delivered`
- `email.opened`
- `email.clicked`
- `email.bounced`
- `email.complained`
- `email.failed`
- `email.delivery_delayed`

The production adapter must verify Svix signatures before parsing the event. The open-source skeleton leaves provider-signature verification as an explicit integration boundary rather than quietly substituting a different HMAC scheme.

## Metrics

Metrics are reported with numerator and denominator:

- delivered / planned;
- opened / delivered;
- opt-in / delivered;
- opt-in / page visitors;
- book issued / opt-in;
- book download completed / opt-in;
- onboarding engaged / opt-in;
- downstream action / opt-in;
- bounce, complaint, unsubscribe, and failed-send guardrails.

Metrics are grouped by campaign, batch, variant, source list, and behavioral cohort. No public endpoint returns raw recipients.

## Deployment status

Prepared locally only. No VPS files, systemd units, DNS records, Resend webhooks, sends, or repository publication have been changed by this repository.
