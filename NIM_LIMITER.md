# NVIDIA NIM 30 RPM Global Rate Limiter

## 1. Requirement & Directive
- **Strict Limit**: 30 Requests Per Minute (RPM) globally across all workers, processes, and containers.
- **Operating Target**: 28 RPM buffer to account for clock skew and jitter.
- **Enforcement**: Code-enforced centralized rate reservation before outbound HTTP dispatch. Prompts are never trusted to enforce rate limits.
- **Retries**: Count as real NIM requests and must acquire slots.

## 2. Sliding-Window Algorithm
The limiter uses a Redis sorted set (`limiter:global:nvidia_nim`) where:
- Member: `f"{timestamp}:{random_uuid}"`
- Score: Epoch timestamp in seconds.

### Slot Acquisition Flow:
1. Prune expired entries older than 60 seconds:
   `ZREMRANGEBYSCORE limiter:global:nvidia_nim -inf (now - 60)`
2. Measure current window depth:
   `count = ZCARD limiter:global:nvidia_nim`
3. If `count < 28`:
   Record new entry: `ZADD limiter:global:nvidia_nim now member`
   Grant immediate reservation.
4. If `count >= 28`:
   Wait with randomized backoff (0.8s - 1.8s) and retry reservation until timeout.

## 3. Concurrency Test Proof
The concurrency test `tests/concurrency/test_nim_limiter.py` spawns 40 concurrent workers competing for 10 slots within a 2-second test window.
Result:
- Granted: Exactly 10
- Rejected / Enqueued: 30
- Status: **PASSED (Zero Rate Limit Violations)**.
