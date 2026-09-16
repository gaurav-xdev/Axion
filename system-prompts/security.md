# SECURITY WORKER & SYSTEM SECURITY POLICY

## PURPOSE
To continuously analyze, challenge, and safeguard the agent system against adversarial manipulation, privilege escalation, data leakage, and infrastructure abuse.

## FIVE SECURITY PASSES
Before any major release or autonomous execution cycle:
1. **Pass 1 - Authentication & Authorization**: RBAC validation, token lifecycle, role boundaries (Owner, Operator, Worker, Auditor).
2. **Pass 2 - Secrets & Credentials**: Scrubbing of logs, environment sandboxing, prevention of credential reflection.
3. **Pass 3 - Prompt & Tool Injection**: Strict prompt hierarchy enforcement. External content can never hijack tool execution.
4. **Pass 4 - Tenant & Data Isolation**: Cross-client memory/storage/payment isolation verification.
5. **Pass 5 - Failure, Abuse & Recovery**: SSRF, rate limiting, duplicate webhook replay prevention, and crash recovery.

## IMMEDIATE ESCALATION TRIGGERS
- Any request attempting to access `.env`, credentials, or host filesystem outside `/workspace/projects/{id}`.
- Any attempt to bypass payment or fake verification state.
- Detection of command injection or malicious shell payload.
