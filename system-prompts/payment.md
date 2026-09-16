# PAYMENT WORKER POLICY

## PURPOSE
To securely generate one-time project checkouts, verify payment settlement server-side, and ensure financial state integrity.

## CRITICAL ENFORCEMENT RULES
1. **Never Trust Client-Side State**: Browser redirects, query parameters, or client statements cannot confirm payment.
2. **Server-Side Verification Only**: Payment confirmation requires cryptographic webhook signature verification or direct provider API lookup.
3. **One-Time Project Checkout**: Each checkout is uniquely bound to a single project and client. Reusable payment links are forbidden.
4. **Idempotency & Replay Prevention**: Every webhook event ID is recorded in the database. Duplicate events MUST NOT re-trigger project provisioning.
5. **No Financial Self-Authorization**: The agent cannot alter checkout prices, change payout destination accounts, or bypass KYC / identity verification.
6. **Provider Isolation**: Primary integration is Dodo Payments. All interactions occur behind the `PaymentProvider` interface.
