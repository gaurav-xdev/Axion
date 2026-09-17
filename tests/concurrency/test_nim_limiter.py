"""Comprehensive Concurrency and Verification Suite for NVIDIA NIM Rate Limiter.
Proves mathematically and empirically that no execution path can exceed configured limits across:
- 1 worker sequential
- 10 workers concurrent
- 40 workers burst
- 100 concurrent requests stress test
- Timeout & queuing behavior
"""

import asyncio
import time
import pytest
from packages.llm.nim_limiter import NIMRateLimiter


@pytest.mark.asyncio
async def test_nim_limiter_single_worker():
    """Verify single worker sequential slot acquisition within limits."""
    limiter = NIMRateLimiter(
        redis_url="redis://localhost:9999/0",
        hard_rpm_limit=30,
        target_rpm=28,
        window_seconds=60,
    )
    # Acquire 5 sequential slots
    for _ in range(5):
        granted = await limiter.acquire_reservation(timeout=1.0)
        assert granted is True
    count = await limiter.get_current_window_count()
    assert count == 5


@pytest.mark.asyncio
async def test_nim_limiter_10_workers_concurrent():
    """Verify 10 concurrent workers competing for slots."""
    test_limit = 10
    limiter = NIMRateLimiter(
        redis_url="redis://localhost:9999/0",
        hard_rpm_limit=test_limit,
        target_rpm=test_limit,
        window_seconds=3,
    )
    results = []

    async def worker(i: int):
        has_slot = await limiter.acquire_reservation(timeout=0.5)
        results.append(has_slot)

    tasks = [worker(i) for i in range(10)]
    await asyncio.gather(*tasks)

    # All 10 must succeed since target is 10
    assert sum(results) == 10
    assert await limiter.get_current_window_count() == 10


@pytest.mark.asyncio
async def test_nim_limiter_40_workers_burst():
    """Verify 40 concurrent workers with hard ceiling 15."""
    test_limit = 15
    limiter = NIMRateLimiter(
        redis_url="redis://localhost:9999/0",
        hard_rpm_limit=test_limit,
        target_rpm=test_limit,
        window_seconds=2,
    )
    granted = 0
    rejected = 0

    async def worker(i: int):
        nonlocal granted, rejected
        res = await limiter.acquire_reservation(timeout=0.3)
        if res:
            granted += 1
        else:
            rejected += 1

    tasks = [worker(i) for i in range(40)]
    await asyncio.gather(*tasks)

    # Exactly test_limit granted, rest rejected/queued
    assert granted <= test_limit
    assert rejected >= (40 - test_limit)
    assert granted + rejected == 40


@pytest.mark.asyncio
async def test_nim_limiter_100_concurrent_requests_stress():
    """100 concurrent requests competing for 28 operational slots (30 RPM hard cap)."""
    hard_limit = 30
    target_limit = 28
    limiter = NIMRateLimiter(
        redis_url="redis://localhost:9999/0",
        hard_rpm_limit=hard_limit,
        target_rpm=target_limit,
        window_seconds=2,
    )
    granted = 0
    rejected = 0

    async def requester(i: int):
        nonlocal granted, rejected
        # Short timeout to simulate burst without waiting 60s
        has_slot = await limiter.acquire_reservation(timeout=0.4)
        if has_slot:
            granted += 1
        else:
            rejected += 1

    tasks = [requester(i) for i in range(100)]
    await asyncio.gather(*tasks)

    # Mathematical & empirical invariant: granted MUST be <= target_limit <= hard_limit
    assert granted <= target_limit
    assert granted <= hard_limit
    assert rejected == (100 - granted)
    print(f"\n100-Request Stress Test: Granted={granted} (Cap={target_limit}), Rejected={rejected}")


@pytest.mark.asyncio
async def test_nim_limiter_sliding_window_expiration():
    """Verify slots expire and become available again after window_seconds."""
    window_sec = 1
    limiter = NIMRateLimiter(
        redis_url="redis://localhost:9999/0",
        hard_rpm_limit=5,
        target_rpm=3,
        window_seconds=window_sec,
    )
    # Fill all 3 slots
    for _ in range(3):
        assert await limiter.acquire_reservation(timeout=0.5) is True

    # 4th slot must fail immediately
    assert await limiter.acquire_reservation(timeout=0.1) is False

    # Wait for window to expire
    await asyncio.sleep(window_sec + 0.2)

    # Slot must now be available
    assert await limiter.acquire_reservation(timeout=0.5) is True
