# System Architecture & Technical Specifications

## 1. High-Level Topology

```
                     AUTONOMOUS MANAGER
                              │
         ┌────────────────────┼────────────────────┐
         │                    │                    │
    Opportunity          Communication       Project Manager
      Engine                 Engine                │
         │                    │                    │
         └────────────────────┼────────────────────┘
                              │
                           Planner
                              │
                ┌─────────────┼─────────────┐
                │             │             │
             Research       Build          QA
                │             │             │
                │       ┌─────┼─────┐       │
                │       │     │     │       │
                │      Code  n8n  Video     │
                │       │     │     │       │
                └───────┼─────┼─────┼───────┘
                              │
                          Delivery
                              │
                           Payment (Dodo HMAC Server-Side)
                              │
                           Records (Authoritative PostgreSQL)
```

---

## 2. Asynchronous State Machine Runtime

The agent operates as a deterministic finite-state machine over database records:
1. `AgentRun` tracks goal, step count, tool count, total cost, and checkpoint state.
2. Every action records an `AgentStep` with thought, action type, payload, and verification status.
3. If an unhandled exception or process termination occurs, the runtime inspects the last checkpoint in PostgreSQL and safely resumes without duplicating external side effects.

### Project States
`DISCOVERED` → `QUALIFYING` → `CONTACT_PENDING` → `CONTACTED` → `CONVERSATION_ACTIVE` → `INTERESTED` → `REQUIREMENTS_PENDING` → `QUALIFIED` → `QUOTE_PENDING` → `QUOTE_SENT` → `PAYMENT_PENDING` → `PAID` → `PLANNING` → `EXECUTING` → `QA` → `DELIVERY_PENDING` → `DELIVERED` → `COMPLETED`.

---

## 3. LLM Provider Routing & Global NIM Limiter

- **Primary**: Ollama Cloud handles routine classification, standard planning, browser steps, simple coding, and normal conversations.
- **Secondary**: NVIDIA NIM handles deep reasoning, architecture analysis, and complex debugging.
- **Global NIM Limit**: Non-negotiable hard ceiling of **30 Requests Per Minute (Target: 28 RPM)** globally across all workers and containers.
- **Enforcement**: Redis-backed sliding window utilizing atomic Lua/multi-exec pipelines (`ZREMRANGEBYSCORE`, `ZCARD`, `ZADD`) with atomic asyncio fallback locks for test isolation.
- **Router Logic**: Calculates composite task score `(complexity * 0.4) + (ambiguity * 0.2) + (risk * 0.2) + (failure_cost * 0.2)`. Routes to NIM only when score > 0.65 or task requires deep architectural reasoning.

---

## 4. Central Tool Gateway Pipeline

Every tool execution passes through 6 mandatory gates:
```
LLM Request 
  → 1. Schema Validation (Pydantic model validation)
  → 2. Permission Check (RBAC: Owner, Operator, Auditor, Worker)
  → 3. Risk Classification (READ_ONLY, LOW, MEDIUM, HIGH, CRITICAL)
  → 4. Policy Engine & SSRF Validation (Private IP / Metadata rejection)
  → 5. Budget Check (Max steps & cost ceilings)
  → 6. Sandboxed Execution (/workspace/projects/{id}/)
  → Output Sanitization (Centralized Secret Redaction)
  → Authoritative DB Audit & Metrics
```

---

## 5. Independent QA & Five-Layer Verification

QA operates as an adversarial entity independent of the coding worker:
- **Check 1: Input Validation**: Schema validation, project ownership, metadata presence.
- **Check 2: Security & Policy Compliance**: Path containment, no secret reflection, no unauthorized privilege requests.
- **Check 3: Execution Verification**: Return code 0, physical file existence, non-zero file byte size.
- **Check 4: Independent Functional Inspection**: Code parsing, exclusion of TODO / placeholder stubs, verification of required acceptance criteria.
- **Check 5: Final State & Evidence**: Cryptographic SHA-256 generation, destination integrity, and database audit record.

---

## 6. Payment Security & Dodo Payments Architecture

- Browser redirects, screenshots, and client messages are strictly untrusted.
- Verification occurs server-side via cryptographic **HMAC-SHA256** webhook signatures.
- Replay attacks and duplicate events are neutralized via unique constraints on `payment_events.event_id`.
- Cross-client payment mismatches (e.g., Client A paying for Client B's project) are rejected immediately as security violations.
