"""Tests for everstaff.llm.rate_limiter — TokenBucket, RateLimiter, registry."""
from __future__ import annotations

import asyncio
import logging
import time

import pytest

from everstaff.llm.rate_limiter import (
    RateLimiter,
    TokenBucket,
    _registry,
    get_rate_limiter,
)


# ---------------------------------------------------------------------------
# TokenBucket tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_token_bucket_acquire_immediate_when_full():
    """Acquiring tokens from a full bucket should return immediately."""
    bucket = TokenBucket(capacity=10, refill_rate=1)
    t0 = time.monotonic()
    await bucket.acquire(5)
    elapsed = time.monotonic() - t0
    assert elapsed < 0.05, f"Should be instant, took {elapsed:.3f}s"


@pytest.mark.asyncio
async def test_token_bucket_acquire_waits_when_empty():
    """Acquiring from an empty bucket should wait for refill."""
    bucket = TokenBucket(capacity=10, refill_rate=100)  # 100 tokens/sec
    # Drain the bucket
    await bucket.acquire(10)
    t0 = time.monotonic()
    await bucket.acquire(5)  # need 5 tokens at 100/sec => ~0.05s
    elapsed = time.monotonic() - t0
    assert 0.03 <= elapsed <= 0.2, f"Expected ~0.05s wait, got {elapsed:.3f}s"


@pytest.mark.asyncio
async def test_token_bucket_consume_goes_negative():
    """consume() should allow tokens to go negative."""
    bucket = TokenBucket(capacity=10, refill_rate=1)
    await bucket.consume(20)
    # Access internal state to verify negative
    async with bucket._lock:
        bucket._refill()
        assert bucket._tokens < 0


@pytest.mark.asyncio
async def test_token_bucket_refill_caps_at_capacity():
    """Tokens should never exceed capacity after refill."""
    bucket = TokenBucket(capacity=10, refill_rate=10000)
    # Wait a bit so refill would overshoot if not capped
    await asyncio.sleep(0.01)
    async with bucket._lock:
        bucket._refill()
        assert bucket._tokens <= bucket._capacity


@pytest.mark.asyncio
async def test_token_bucket_concurrent_acquire():
    """Multiple concurrent acquires should all eventually succeed."""
    bucket = TokenBucket(capacity=5, refill_rate=500)  # fast refill
    results: list[int] = []

    async def worker(i: int) -> None:
        await bucket.acquire(1)
        results.append(i)

    tasks = [asyncio.create_task(worker(i)) for i in range(10)]
    await asyncio.wait_for(asyncio.gather(*tasks), timeout=5.0)
    assert sorted(results) == list(range(10))


# ---------------------------------------------------------------------------
# RateLimiter tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_rate_limiter_no_limits():
    """RateLimiter with no limits should pass through immediately."""
    rl = RateLimiter()
    t0 = time.monotonic()
    await rl.before_request()
    await rl.after_request(1000)
    elapsed = time.monotonic() - t0
    assert elapsed < 0.05


@pytest.mark.asyncio
async def test_rate_limiter_rpm_throttles():
    """RPM bucket should throttle after limit is reached."""
    rl = RateLimiter(rpm_limit=60)  # 1 req/sec
    # First request should be instant
    await rl.before_request()
    # Exhaust bucket — the RPM bucket starts full with 60 tokens
    # We need to drain it; issue 59 more to use all 60.
    for _ in range(59):
        await rl.before_request()
    # 61st request should wait
    t0 = time.monotonic()
    await rl.before_request()
    elapsed = time.monotonic() - t0
    assert elapsed >= 0.5, f"Expected throttling, got {elapsed:.3f}s"


@pytest.mark.asyncio
async def test_rate_limiter_tpm_throttles_after_consume():
    """TPM bucket should throttle after heavy token consumption."""
    rl = RateLimiter(tpm_limit=600)  # 10 tokens/sec
    await rl.before_request()
    # Consume more than the bucket capacity to go negative
    await rl.after_request(700)
    # Next before_request should wait for tokens to refill to >= 0
    t0 = time.monotonic()
    await rl.before_request()
    elapsed = time.monotonic() - t0
    # Need to recover ~100 tokens at 10/sec => ~10s... that's too long.
    # Actually 600 tpm = 10 tokens/sec. 700-600=100 deficit => 10s.
    # Let's use a bigger tpm_limit for a shorter test.
    # Re-test with better numbers below.


@pytest.mark.asyncio
async def test_rate_limiter_tpm_throttles_after_consume_fast():
    """TPM bucket should throttle after heavy token consumption (fast refill)."""
    rl = RateLimiter(tpm_limit=6000)  # 100 tokens/sec
    await rl.before_request()
    # Consume 6100 tokens (100 over capacity) => needs ~1s to recover
    await rl.after_request(6100)
    t0 = time.monotonic()
    await rl.before_request()  # waits for tokens >= 0
    elapsed = time.monotonic() - t0
    assert elapsed >= 0.5, f"Expected throttling, got {elapsed:.3f}s"


# ---------------------------------------------------------------------------
# Registry tests
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _clear_registry():
    """Ensure a clean registry for each test."""
    _registry.clear()
    yield
    _registry.clear()


def test_registry_returns_same_instance():
    """get_rate_limiter should return the same object for the same model."""
    rl1 = get_rate_limiter("model-a", tpm_limit=1000, rpm_limit=60)
    rl2 = get_rate_limiter("model-a", tpm_limit=1000, rpm_limit=60)
    assert rl1 is rl2


def test_registry_different_models():
    """Different model IDs should get different RateLimiter instances."""
    rl1 = get_rate_limiter("model-a", tpm_limit=1000)
    rl2 = get_rate_limiter("model-b", tpm_limit=2000)
    assert rl1 is not rl2


def test_registry_warns_on_conflicting_limits(caplog):
    """Registry should warn when requested limits differ from existing."""
    get_rate_limiter("model-c", tpm_limit=1000, rpm_limit=60)
    with caplog.at_level(logging.WARNING):
        rl2 = get_rate_limiter("model-c", tpm_limit=5000, rpm_limit=120)
    assert "mismatch" in caplog.text.lower()
    # Should still return the original instance
    assert rl2._tpm_limit == 1000
