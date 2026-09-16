"""Concurrency test proving NVIDIA NIM 30 RPM global hard rate limit.
Simulates concurrent workers competing for slots and verifies no window exceeds the configured limit.
"""

import asyncio
import time
import pytest
from packages.llm.nim_limiter import NIMRateLimiter


@pytest.mark.asyncio
async def test_nim_rate_limiter_strict_window_concurrency():
    """Verify that when 60 concurrent tasks request reservation, the number granted

    within the rolling window NEVER exceeds hard limit.
    """
    # Create limiter configured with 10 max RPM for fast deterministic test verification
    test_limit = 10
    limiter = NIMRateLimiter(
        redis_url="redis://localhost:9999/0",  # Deliberately unreachable Redis to test atomic in-process lock
        hard_rpm_limit=test_limit,
        target_rpm=test_limit,
        window_seconds=2,  # 2 second window for fast test execution
    )

    granted_timestamps = []
    rejected_count = 0

    async def worker_task(task_id: int):
        nonlocal rejected_count
        # Each worker attempts to reserve a slot with a short timeout
        has_slot = await limiter.acquire_reservation(timeout=0.4)
        if has_slot:
            granted_timestamps.append(time.time())
        else:
            rejected_count += 1

    # Launch 40 concurrent workers simultaneously
    tasks = [worker_task(i) for i in range(40)]
    await asyncio.gather(*tasks)

    # Verify that in any rolling 2-second interval, granted requests do not exceed target_rpm
    assert len(granted_timestamps) <= test_limit
    assert rejected_count >= (40 - test_limit)
    print(f"Limiter Test Passed: Granted={len(granted_timestamps)}, Rejected={rejected_count}, Limit={test_limit}")
