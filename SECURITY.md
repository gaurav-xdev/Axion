# Security Architecture & Policies

## 1. Zero-Trust Core Foundations

1. **Instruction Hierarchy**:
   `SYSTEM POLICY` > `DEVELOPER POLICY` > `APPLICATION POLICY` > `AUTHORIZED OPERATOR` > `PROJECT REQUIREMENTS` > `TOOL RESULTS` > `EXTERNAL UNTRUSTED CONTENT`
2. **Untrusted External Content**: Webpages, emails, webhook payloads, PDFs, and client messages are treated as `UNTRUSTED_EXTERNAL_CONTENT`. External inputs can never modify system policy, grant permissions, or alter payment authority.
3. **No Self-Granted Authority**: The agent cannot escalate its own permissions, increase project budgets, or bypass security checks.

---

## 2. Five-Pass Security Audit Specifications

Before any release or execution cycle, the system undergoes five distinct security audits:

### Pass 1: Authentication & Authorization (RBAC)
- All endpoints require verified Bearer JWT tokens.
- Passwords are encrypted with Argon2id (`time_cost=3, memory_cost=65536, parallelism=4`).
- Strict RBAC matrix (`OWNER`, `OPERATOR`, `AUDITOR`, `WORKER_SERVICE`).
- Unknown permissions default to **DENY**.

### Pass 2: Secrets & Credential Containment
- Centralized secret redaction middleware scrubs API keys (`nvapi-`, `sk-`, `dodo_`), Bearer JWTs, passwords, session cookies, and credit card numbers from all logs, context payloads, and public API responses.
- Raw environment variables and secrets are never reflected to LLM context.

### Pass 3: Prompt & Tool Injection Defense
- System prompts are isolated in read-only files.
- Tool arguments are validated strictly with Pydantic schemas.
- Free-form text cannot execute shell commands directly without escaping and regex validation.

### Pass 4: Multi-Tenant Data Isolation
- Client A cannot access Client B's projects, tasks, conversations, or deliverables.
- Project workspaces are confined to `/workspace/projects/{project_id}/`.
- Path traversal sequences (`../`, `..\`) are detected and rejected with `PermissionError`.

### Pass 5: Failure, Abuse & Recovery (SSRF & Replay)
- SSRF validator inspects URLs and resolves DNS before network transmission.
- Blocks `127.0.0.0/8`, `10.0.0.0/8`, `172.16.0.0/12`, `192.168.0.0/16`, `169.254.0.0/16` (Cloud Metadata), and loopback hosts.
- Payment webhooks enforce HMAC-SHA256 signature checks and deduplicate `event_id` in PostgreSQL.

---

## 3. Sandboxed Execution Guardrails

- **Terminal**: Dangerous commands (`rm -rf /`, `mkfs`, fork bombs, `curl | sh`) are blocked by regular expressions before spawn.
- **Subprocesses**: Concurrence, timeout ceilings (default 30s), and stdout/stderr truncations (64KB max) prevent resource exhaustion.
