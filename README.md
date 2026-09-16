# Autonomous Business Operating Platform

A serious, production-grade, highly autonomous AI business operator designed to autonomously execute the complete commercial lifecycle:
**Opportunity Discovery → Research → Qualification → Personalized Outreach → Scoping & Acceptance → One-Time Checkout → Server-Side Verified Payment → Sandboxed Execution → Independent 5-Layer QA → Delivery Packaging → State Completion**.

---

## Non-Negotiable Core Architecture Principles

1. **State + Policy + Tools + Memory + Execution + Verification + Observability**: The LLM is a reasoning component, not the system architecture. All critical restrictions, rate limits, state transitions, and boundaries are enforced in code.
2. **NVIDIA NIM Hard Global Limit (30 RPM)**: Code-enforced centralized rate limiter backed by Redis atomic sliding window (or in-process lock). Shared across all workers, processes, and containers. Retries count toward the limit.
3. **Primary LLM Provider**: Ollama Cloud as primary low-cost default; NVIDIA NIM as secondary for complex architecture and deep reasoning.
4. **n8n Boundary**: n8n is strictly a **client deliverable target**. The agent's internal orchestration backbone is a native Python asynchronous state-machine runtime.
5. **Dodo Payments Server-Side Verification**: Browser redirects and client messages are strictly untrusted. Payment settlement is confirmed exclusively via cryptographic HMAC-SHA256 webhook signatures and deduplicated event records.
6. **Zero-Spam Outreach**: Every message passes a 10-point anti-spam verification check before dispatch.
7. **Least Privilege & Tenant Isolation**: Every project runs in `/workspace/projects/{project_id}/`. Path traversal and SSRF are blocked at the gateway level.
8. **Independent Adversarial QA**: Workers cannot approve their own deliverables. QA performs 5 independent checks (Input, Security, Execution, Functional, Final State) and can reject back to execution.

---

## Tech Stack

- **Backend**: Python 3.11+, FastAPI, Pydantic v2, SQLAlchemy 2.0 Async, PostgreSQL 16+ / SQLite (aiosqlite), Redis 7+, httpx, asyncio
- **Browser Automation**: Playwright + Chromium with isolated browser contexts and strict SSRF filters
- **Media**: FFmpeg and ffprobe stream verification
- **Frontend**: React, Vite, TypeScript, Tailwind CSS, TanStack Query, Lucide Icons
- **Security**: Argon2id password hashing, short-lived JWTs, HMAC-SHA256, centralized secret redaction
- **Observability**: Prometheus-compatible metrics (`/metrics`), structured JSON logs with correlation IDs

---

## Directory Layout

```
├── apps/
│   ├── api/             # FastAPI REST endpoints, webhooks, middleware
│   ├── worker/          # Background worker service loop
│   ├── scheduler/       # Scheduled jobs and pipeline monitoring
│   ├── browser-worker/  # Isolated Playwright execution worker
│   └── dashboard/       # React + Vite + Tailwind dashboard
├── packages/
│   ├── agent/           # State machine, asynchronous runtime, lifecycle engine
│   ├── llm/             # Ollama & NIM providers, router, global 30 RPM limiter
│   ├── tools/           # Central Tool Gateway, sandboxed filesystem, terminal, SSRF
│   ├── browser/         # BrowserWorker with context isolation
│   ├── computer/        # ComputerDriver abstraction
│   ├── memory/          # Targeted context retrieval & relational state
│   ├── projects/        # Prospecting engine & Project acceptance engine
│   ├── communications/  # Email, WhatsApp, Voice gateways & 10-point anti-spam
│   ├── payments/        # Dodo Payments provider & server-side verification
│   ├── security/        # Auth, RBAC, secret redaction, 5-pass security audit
│   ├── qa/              # Independent QAWorker with 5-layer verification
│   ├── automation/      # Client n8n workflow generation & schema validation
│   ├── media/           # FFmpeg/ffprobe video inspection & verification
│   ├── observability/   # Prometheus metrics & JSON logger with redaction
│   └── shared/          # Pydantic settings, database engine, SQLAlchemy models
├── system-prompts/      # Versioned markdown policy files
├── tests/
│   ├── unit/            # Auth, RBAC, acceptance engine unit tests
│   ├── security/        # SSRF, redaction, path traversal, 5-pass audit tests
│   ├── integration/     # Payment webhook, replay attack & mismatch tests
│   ├── concurrency/     # NIM global 30 RPM limiter concurrency test
│   └── e2e/             # Complete sandbox commercial lifecycle test
└── docker-compose.yml   # Multi-container production deployment topology
```

---

## Quickstart

### 1. Environment Setup
```bash
# Clone and enter directory
cd "The earner agent"

# Virtual environment setup
python -m venv .venv
.\.venv\Scripts\activate

# Install dependencies in editable mode with dev tools
pip install -e ".[dev]"
```

### 2. Configure Environment
Copy `.env.example` to `.env` and configure your credentials:
```bash
cp .env.example .env
```

### 3. Run Automated Tests
```bash
pytest tests/ -v
```

### 4. Start the Application
**Backend API Server**:
```bash
uvicorn apps.api.main:app --host 0.0.0.0 --port 8000 --reload
```

**Frontend Dashboard**:
```bash
cd apps/dashboard
npm install --legacy-peer-deps
npm run dev
```
Navigate to `http://localhost:3000` to inspect live agent telemetry, emergency controls, projects, payments, and run the 5-pass security audit.
