# Payment Architecture & Dodo Payments Integration

## 1. Non-Negotiable Verification Rules
- **Server-Side Verification Only**: Browser redirects, client messages ("I have paid"), or frontend states are NEVER treated as payment proof.
- **HMAC-SHA256 Webhook Signatures**: Inbound webhooks must match the cryptographic HMAC signature generated with `DODO_WEBHOOK_SECRET`.
- **Deduplication & Idempotency**: Each event ID is recorded in the `payment_events` table. Duplicate events return success immediately without re-triggering project provisioning.
- **One-Time Project Checkout**: Checkouts are strictly bound to a single `project_id` and `client_id`. Reusable links are prohibited.
- **Cross-Client Isolation**: Webhooks referencing mismatched `client_id` for a project are rejected as critical security violations.

## 2. Tax & Merchant-of-Record (MoR) Boundary
Dodo Payments acts as the Merchant of Record for customer-facing sales tax / VAT where configured.
However, the software does not provide legal or tax advice. Any ambiguous cross-border corporate tax inquiries are flagged as `ESCALATE`.
