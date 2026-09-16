# Automated Testing & Verification Suite

The repository features comprehensive automated test coverage across 5 dimensions:

## 1. Concurrency & Rate Limiting
- `tests/concurrency/test_nim_limiter.py`:
  Proves that under 40 concurrent worker requests, the global limiter grants at most the target capacity within the rolling window and queues/rejects the excess.

## 2. Security & Penetration Audits
- `tests/security/test_security_passes.py`:
  - SSRF test: Blocks localhost, RFC1918 private IPs, and AWS/GCP/Azure link-local metadata endpoints (`169.254.169.254`).
  - Secret redaction test: Validates regex masking for `nvapi-`, `sk-`, JWTs, passwords, and authorization headers.
  - Path traversal test: Verifies that escaping `/workspace/projects/{id}/` raises `PermissionError`.
  - Dangerous commands test: Verifies regex rejection of `rm -rf /`, `mkfs`, fork bombs, etc.
  - 5-Pass Security Audit: Automated execution of the full 5-pass security suite.

## 3. Webhook & Integration Safety
- `tests/integration/test_payment_webhook.py`:
  - Tests valid HMAC-SHA256 signature acceptance and state transition to `PAID`.
  - Tests invalid signature rejection.
  - Tests idempotent duplicate event handling (Directive 10).
  - Tests cross-client payment metadata mismatch rejection.

## 4. End-to-End Business Lifecycle
- `tests/e2e/test_autonomous_lifecycle.py`:
  - Complete execution of Prospecting → Qualification → Anti-Spam Check → Outreach → Acceptance Evaluation → Quote Generation → Checkout Creation → Server-Side Webhook Verification → Paid Unlock → Sandboxed Coding Execution → Independent 5-Layer QA Verification → Delivery Packaging → State Completion.

## 5. Running the Tests
```bash
# Execute entire test suite
pytest tests/ -v
```
