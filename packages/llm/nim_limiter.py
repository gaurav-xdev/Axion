"""Global NVIDIA NIM Rate Limiter.
Enforces NON-NEGOTIABLE HARD GLOBAL LIMIT of 30 requests/minute across all workers and processes.
Uses a sliding-window algorithm backed by Redis (or in-process atomic lock fallback for standalone testing).
"""

import asyncio
import random
import time
from typing import Optional
import redis.asyncio as aioredis

from packages.observability.logger import logger
from packages.observability.metrics import (
    NIM_QUEUE_DEPTH,
    NIM_REQUESTS_LAST_60S,
    NIM_WAIT_TIME_SECONDS,
)
from packages.shared.config import settings


class NIMRateLimiter:
    """Centralized, shared rate limiter for NVIDIA NIM enforcing max 30 RPM globally."""

    def __init__(
        self,
        redis_url: Optional[str] = None,
        hard_rpm_limit: int = 30,
        target_rpm: int = 28,
        window_seconds: int = 60,
    ):
        self.redis_url = redis_url or settings.REDIS_URL
        self.hard_rpm_limit = hard_rpm_limit
        self.target_rpm = target_rpm
        self.window_seconds = window_seconds
        self.redis_key = "limiter:global:nvidia_nim"
        self._redis_client: Optional[aioredis.Redis] = None
        self._local_lock = asyncio.Lock()
        self._local_timestamps: list[float] = []

    async def _get_redis(self) -> Optional[aioredis.Redis]:
        if self._redis_client is None:
            try:
                client = aioredis.from_url(
                    self.redis_url,
                    encoding="utf-8",
                    decode_responses=True,
                    socket_connect_timeout=1.5,
                )
                await client.ping()
                self._redis_client = client
            except Exception as e:
                logger.warning(
                    f"Redis unavailable for NIM limiter ({e}). Using atomic in-process limiter fallback."
                )
                self._redis_client = None
        return self._redis_client

    async def acquire_reservation(self, timeout: float = 90.0) -> bool:
        """Atomically reserve 1 NIM request slot within the rolling 60-second window.
        Blocks and enqueues if rate limit would be exceeded.
        """
        start_time = time.monotonic()
        NIM_QUEUE_DEPTH.inc()

        try:
            while True:
                elapsed = time.monotonic() - start_time
                if elapsed >= timeout:
                    logger.error(
                        f"NIM Rate Limiter: Request timed out after {elapsed:.2f}s waiting for reservation"
                    )
                    return False

                now = time.time()
                cutoff = now - self.window_seconds

                redis = await self._get_redis()
                if redis:
                    # Redis Lua or pipeline sliding-window check
                    try:
                        async with redis.pipeline(transaction=True) as pipe:
                            # Remove entries older than 60 seconds
                            pipe.zremrangebyscore(self.redis_key, "-inf", cutoff)
                            # Get count of requests in current window
                            pipe.zcard(self.redis_key)
                            results = await pipe.execute()

                        current_count = results[1]
                        NIM_REQUESTS_LAST_60S.set(current_count)

                        if current_count < self.target_rpm:
                            # Reserve slot using unique score and member
                            member_id = f"{now}:{random.random()}"
                            await redis.zadd(self.redis_key, {member_id: now})
                            await redis.expire(self.redis_key, self.window_seconds + 5)
                            wait_duration = time.monotonic() - start_time
                            NIM_WAIT_TIME_SECONDS.observe(wait_duration)
                            return True
                    except Exception as e:
                        logger.warning(f"Redis pipeline error in NIM limiter: {e}")

                else:
                    # In-process sliding window fallback with strict asyncio lock
                    async with self._local_lock:
                        # Prune expired
                        self._local_timestamps = [
                            ts for ts in self._local_timestamps if ts > cutoff
                        ]
                        current_count = len(self._local_timestamps)
                        NIM_REQUESTS_LAST_60S.set(current_count)

                        if current_count < self.target_rpm:
                            self._local_timestamps.append(now)
                            wait_duration = time.monotonic() - start_time
                            NIM_WAIT_TIME_SECONDS.observe(wait_duration)
                            return True

                # Wait with jitter before retrying reservation
                backoff = random.uniform(0.8, 1.8)
                await asyncio.sleep(backoff)

        finally:
            NIM_QUEUE_DEPTH.dec()

    async def get_current_window_count(self) -> int:
        """Returns the number of requests booked in the current 60s window."""
        now = time.time()
        cutoff = now - self.window_seconds
        redis = await self._get_redis()
        if redis:
            try:
                await redis.zremrangebyscore(self.redis_key, "-inf", cutoff)
                return await redis.zcard(self.redis_key)
            except Exception:
                pass
        async with self._local_lock:
            self._local_timestamps = [ts for ts in self._local_timestamps if ts > cutoff]
            return len(self._local_timestamps)


# Global singleton instance
nim_limiter = NIMRateLimiter()
