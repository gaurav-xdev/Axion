"""Prometheus-compatible metrics instrumentation for observability.
"""

from prometheus_client import Counter, Gauge, Histogram

# Agent Runs
AGENT_RUNS_TOTAL = Counter("agent_runs_total", "Total agent runs initiated", ["status"])
AGENT_RUNS_FAILED = Counter("agent_runs_failed", "Total failed agent runs")
AGENT_RUNS_COMPLETED = Counter("agent_runs_completed", "Total successfully completed agent runs")

# Tools
TOOL_CALLS_TOTAL = Counter("tool_calls_total", "Total tool executions requested", ["tool_name", "risk_level"])
TOOL_FAILURES = Counter("tool_failures_total", "Total tool execution failures", ["tool_name"])

# Browser
BROWSER_SESSIONS_ACTIVE = Gauge("browser_sessions_active", "Number of currently active browser worker sessions")

# Projects & QA
ACTIVE_PROJECTS = Gauge("active_projects", "Number of currently active client projects", ["status"])
QA_EVALUATIONS_TOTAL = Counter("qa_evaluations_total", "Total QA evaluations performed", ["status"])
QA_FINDINGS_TOTAL = Counter("qa_findings_total", "Total QA issues identified", ["severity"])

# Payments
PAYMENT_EVENTS_TOTAL = Counter("payment_events_total", "Total payment webhook events received", ["event_type", "status"])
PAYMENT_FAILURES_TOTAL = Counter("payment_failures_total", "Total payment processing failures")

# Communications
MESSAGES_SENT_TOTAL = Counter("messages_sent_total", "Total outbound messages dispatched", ["channel", "status"])
MESSAGES_FAILED_TOTAL = Counter("messages_failed_total", "Total message dispatch failures", ["channel"])

# LLM & NIM Global Limiter Metrics
OLLAMA_REQUESTS_TOTAL = Counter("ollama_requests_total", "Total requests dispatched to Ollama Cloud", ["model", "status"])
NIM_REQUESTS_TOTAL = Counter("nim_requests_total", "Total requests dispatched to NVIDIA NIM", ["model", "status"])
NIM_QUEUE_DEPTH = Gauge("nim_queue_depth", "Current number of requests waiting in NIM rate-limiter queue")
NIM_REQUESTS_LAST_60S = Gauge("nim_requests_last_60_seconds", "Number of NIM requests reserved in rolling 60s window")
NIM_WAIT_TIME_SECONDS = Histogram("nim_wait_time_seconds", "Time spent waiting in NIM rate limiter queue")
