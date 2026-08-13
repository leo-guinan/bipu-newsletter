# Public Release Boundary

Status: local projection; not published.

## Included

- README and MIT license;
- dependency-free Python event ledger;
- Resend transport adapter;
- metrics and webhook endpoint skeleton;
- tests;
- example environment variable names;
- systemd deployment shape.

## Excluded

- subscriber exports and raw email addresses;
- names, locations, and replies;
- provider credentials and webhook secrets;
- book files and private delivery URLs;
- live send logs and provider IDs;
- VPS paths, host credentials, and private environment files;
- BIPU subscriber inventory and campaign recipient assignments.

## Claims this repository does not make

- It does not prove that Resend is configured.
- It does not prove that the Hitchhiker's Guide domain is authenticated for a new sender.
- It does not prove that a VPS deployment exists.
- It does not prove that any email has been sent, delivered, opened, clicked, or opted into.
- It does not provide a finished webhook signature verifier yet.

The project is an open implementation pattern for time-respecting, operator-controlled newsletter infrastructure. A public repository would be infrastructure, not evidence of campaign performance.
