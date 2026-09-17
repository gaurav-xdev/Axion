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


LUA_SLIDING_WINDOW_RESERVATION = """
local key = KEYS[1]
local now = tonumber(ARGV[1])
local window = tonumber(ARGV[2])
local limit = tonumber(ARGV[3])
local member = ARGV[4]

local cutoff = now - window
redis.call('ZREMRANGEBYSCORE', key, '-inf', cutoff)
local current_count = redis.call('ZCARD', key)

if current_count < limit then
    redis.call('ZADD', key, now, member)
    redis.call('EXPIRE', key, math.ceil(window) + 5)
    return {1, current_count + 1}
else
    return {0, current_count}
end
"""


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
        self._redis_last_check: float = 0.0
        self._redis_retry_interval: float = 10.0

    async def _get_redis(self) -> Optional[aioredis.Redis]:
        if self._redis_client is not None:
            return self._redis_client
        now = time.time()
        if now - self._redis_last_check < self._redis_retry_interval:
            return None
        self._redis_last_check = now
        try:
            client = aioredis.from_url(
                self.redis_url,
                encoding="utf-8",
                decode_responses=True,
                socket_connect_timeout=0.5,
            )
            await client.ping()
            self._redis_client = client
            return self._redis_client
        except Exception as e:
            logger.warning(
                f"Redis unavailable for NIM limiter ({e}). Using atomic in-process limiter fallback."
            )
            self._redis_client = None
            return None

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
                    try:
                        member_id = f"{now}:{random.random()}"
                        res = await redis.eval(
                            LUA_SLIDING_WINDOW_RESERVATION,
                            1,
                            self.redis_key,
                            str(now),
                            str(self.window_seconds),
                            str(self.target_rpm),
                            member_id,
                        )
                        granted = bool(res[0] == 1)
                        current_count = int(res[1])
                        NIM_REQUESTS_LAST_60S.set(current_count)

                        if granted:
                            wait_duration = time.monotonic() - start_time
                            NIM_WAIT_TIME_SECONDS.observe(wait_duration)
                            return True
                    except Exception as e:
                        logger.warning(f"Redis Lua execution error in NIM limiter: {e}")

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
