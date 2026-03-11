"""Rate limiting for LLM API calls — per-model TPM/RPM token buckets."""
from __future__ import annotations

import asyncio
import logging
import time

logger = logging.getLogger(__name__)


class TokenBucket:
    """Async token bucket for rate limiting.

    Supports both pre-request gating (acquire) and post-request deduction (consume).
    Refill is lazy — calculated from elapsed time on each access.
    """

    def __init__(self, capacity: float, refill_rate: float) -> None:
        self._capacity = capacity
        self._refill_rate = refill_rate
        self._tokens = capacity
        self._last_refill = time.monotonic()
        self._lock = asyncio.Lock()

    def _refill(self) -> None:
        """Add tokens based on elapsed time. Caller must hold the lock."""
        now = time.monotonic()
        elapsed = now - self._last_refill
        self._tokens = min(self._capacity, self._tokens + elapsed * self._refill_rate)
        self._last_refill = now

    async def acquire(self, amount: float = 1) -> None:
        """Wait until bucket has >= amount tokens, then deduct."""
        _waited = False
        _t0 = time.monotonic()
        while True:
            async with self._lock:
                self._refill()
                if self._tokens >= amount:
                    self._tokens -= amount
                    if _waited:
                        logger.info(
                            "Rate limit wait finished: %.1fs (bucket %.0f/%.0f)",
                            time.monotonic() - _t0, self._tokens, self._capacity,
                        )
                    return
                deficit = amount - self._tokens
                wait = deficit / self._refill_rate
                available = self._tokens
            # Sleep OUTSIDE the lock so other coroutines can proceed
            if not _waited:
                logger.warning(
                    "Rate limit throttling: need %.0f tokens, have %.0f, "
                    "waiting ~%.1fs (bucket capacity=%.0f)",
                    amount, available, wait, self._capacity,
                )
                _waited = True
            await asyncio.sleep(wait)

    async def consume(self, amount: float) -> None:
        """Deduct tokens after request completes. Can go negative."""
        async with self._lock:
            self._refill()
            self._tokens -= amount
            if self._tokens < -self._capacity:
                logger.info(
                    "Token bucket deeply negative: %.0f / %.0f",
                    self._tokens, self._capacity,
                )


class RateLimiter:
    """Composes TPM + RPM token buckets for one model endpoint."""

    def __init__(
        self,
        tpm_limit: int | None = None,
        rpm_limit: int | None = None,
    ) -> None:
        self._tpm_limit = tpm_limit
        self._rpm_limit = rpm_limit
        self._tpm = TokenBucket(tpm_limit, tpm_limit / 60) if tpm_limit else None
        self._rpm = TokenBucket(rpm_limit, rpm_limit / 60) if rpm_limit else None

    async def before_request(self) -> None:
        """Await both RPM and TPM budgets before sending."""
        if self._rpm:
            await self._rpm.acquire(1)
        if self._tpm:
            await self._tpm.acquire(0)  # wait for non-negative

    async def after_request(self, tokens_used: int) -> None:
        """Record actual token consumption."""
        if self._tpm and tokens_used > 0:
            await self._tpm.consume(tokens_used)


_registry: dict[str, RateLimiter] = {}


def get_rate_limiter(
    model_id: str,
    tpm_limit: int | None = None,
    rpm_limit: int | None = None,
) -> RateLimiter:
    """Get or create a RateLimiter for *model_id* (first-registered wins)."""
    existing = _registry.get(model_id)
    if existing is not None:
        if (tpm_limit, rpm_limit) != (existing._tpm_limit, existing._rpm_limit):
            logger.warning(
                "Rate limiter limit mismatch for model '%s': "
                "requested tpm=%s rpm=%s, existing tpm=%s rpm=%s — using existing",
                model_id, tpm_limit, rpm_limit,
                existing._tpm_limit, existing._rpm_limit,
            )
        return existing
    rl = RateLimiter(tpm_limit=tpm_limit, rpm_limit=rpm_limit)
    _registry[model_id] = rl
    if tpm_limit or rpm_limit:
        logger.info(
            "Rate limiter created for '%s': tpm=%s rpm=%s",
            model_id, tpm_limit, rpm_limit,
        )
    return rl
