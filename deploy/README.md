# Deployment boundary

Status: prepared locally; not installed.

## Required external steps

1. Choose the VPS host and destination hostname. The prior `vps-marvin` read-only check found no `/opt/hitchhikers-guide-chat` and no existing BIPU newsletter service.
2. Create a dedicated system user and `/opt/bipu-newsletter` deployment directory.
3. Install the package and systemd unit.
4. Transfer `RESEND_API_KEY` server-side from the existing protected source environment. Never put it in SSH arguments, Git, or chat.
5. Verify the source and destination variable names: `RESEND_API_KEY`, `GUIDE_EMAIL_FROM`, `GUIDE_EMAIL_REPLY_TO`.
6. Add the Resend webhook secret after creating the webhook and implementing Svix verification.
7. Put the service behind an HTTPS hostname with a narrow proxy route:
   - `GET /healthz`
   - `GET /metrics`
   - `POST /webhooks/resend`
8. Verify health and authenticated provider read access without sending an email.
9. Send only after separate send approval and after a synthetic/internal webhook test passes.

## Current blocker

The open-source webhook server intentionally returns `501` until provider signature verification is implemented. Deploying it before that would create a public event-ingestion endpoint that cannot prove authenticity. That is not an acceptable shortcut.
