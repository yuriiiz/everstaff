# LLM Rate Limiting Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add per-model-endpoint TPM/RPM rate limiting with 429 backoff retry to prevent API quota exhaustion.

**Architecture:** A shared `TokenBucket` + `RateLimiter` registry in `llm/rate_limiter.py`, integrated into `LiteLLMClient`. litellm's built-in retry is disabled; our retry loop re-acquires from the rate limiter before each attempt. Config flows from `ModelMapping` → `AgentBuilder` / daemon factory → `LiteLLMClient`.

**Tech Stack:** Python asyncio, pydantic, litellm

**Spec:** `docs/superpowers/specs/2026-03-12-llm-rate-limiting-design.md`

---

## Chunk 1: Core Rate Limiter

### Task 1: Create `TokenBucket` class with tests

**Files:**
- Create: `src/everstaff/llm/rate_limiter.py`
- Create: `tests/test_llm/test_rate_limiter.py`

- [ ] **Step 1: Write failing tests for TokenBucket**

In `tests/test_llm/test_rate_limiter.py`:

```python
"""Tests for llm/rate_limiter.py — TokenBucket and RateLimiter."""
from __future__ import annotations

import asyncio
import time

import pytest


@pytest.mark.asyncio
async def test_token_bucket_acquire_immediate_when_full():
    """acquire() should return immediately when bucket has enough tokens."""
    from everstaff.llm.rate_limiter import TokenBucket

    bucket = TokenBucket(capacity=100, refill_rate=100 / 60)
    start = time.monotonic()
    await bucket.acquire(10)
    elapsed = time.monotonic() - start
    assert elapsed < 0.1  # should be near-instant


@pytest.mark.asyncio
async def test_token_bucket_acquire_waits_when_empty():
    """acquire() should block until tokens refill."""
    from everstaff.llm.rate_limiter import TokenBucket

    bucket = TokenBucket(capacity=10, refill_rate=100)  # 100 tokens/sec refill
    # Drain the bucket
    await bucket.acquire(10)
    start = time.monotonic()
    await bucket.acquire(5)  # need 5 tokens, refill at 100/sec → ~0.05s wait
    elapsed = time.monotonic() - start
    assert 0.01 < elapsed < 0.5


@pytest.mark.asyncio
async def test_token_bucket_consume_goes_negative():
    """consume() can push bucket negative; next acquire waits for refill."""
    from everstaff.llm.rate_limiter import TokenBucket

    bucket = TokenBucket(capacity=100, refill_rate=1000)  # fast refill
    await bucket.consume(200)  # -100 tokens
    start = time.monotonic()
    await bucket.acquire(0)  # wait for non-negative
    elapsed = time.monotonic() - start
    assert elapsed > 0.01  # had to wait


@pytest.mark.asyncio
async def test_token_bucket_refill_caps_at_capacity():
    """Bucket should not refill beyond capacity."""
    from everstaff.llm.rate_limiter import TokenBucket

    bucket = TokenBucket(capacity=50, refill_rate=1000)
    await bucket.acquire(10)  # 40 left
    await asyncio.sleep(0.2)  # would refill 200, but capped at 50
    await bucket.acquire(50)  # should succeed (50 available)
    # Should NOT be able to get more than capacity
    start = time.monotonic()
    await bucket.acquire(1)  # bucket at 0, need to wait
    elapsed = time.monotonic() - start
    assert elapsed > 0.0005


@pytest.mark.asyncio
async def test_token_bucket_concurrent_acquire():
    """Multiple concurrent acquire() calls should not corrupt state."""
    from everstaff.llm.rate_limiter import TokenBucket

    bucket = TokenBucket(capacity=10, refill_rate=1000)  # fast refill

    async def grab():
        await bucket.acquire(3)

    # 4 concurrent grabs of 3 = 12 tokens needed from capacity 10
    # Some will wait briefly, but all should complete
    await asyncio.wait_for(
        asyncio.gather(*[grab() for _ in range(4)]),
        timeout=2.0,
    )
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /Users/bytedance/Projects/cyber_yuri/everstaff && uv run pytest tests/test_llm/test_rate_limiter.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'everstaff.llm.rate_limiter'`

- [ ] **Step 3: Implement TokenBucket**

Create `src/everstaff/llm/rate_limiter.py`:

```python
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
        """
        Args:
            capacity: Maximum tokens in the bucket.
            refill_rate: Tokens added per second.
        """
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
        while True:
            async with self._lock:
                self._refill()
                if self._tokens >= amount:
                    self._tokens -= amount
                    return
                deficit = amount - self._tokens
                wait = deficit / self._refill_rate
            # Sleep OUTSIDE the lock so other coroutines can proceed
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /Users/bytedance/Projects/cyber_yuri/everstaff && uv run pytest tests/test_llm/test_rate_limiter.py -v`
Expected: All 5 tests PASS

- [ ] **Step 5: Commit**

```bash
cd /Users/bytedance/Projects/cyber_yuri/everstaff
git add src/everstaff/llm/rate_limiter.py tests/test_llm/test_rate_limiter.py
git commit -m "feat: add TokenBucket async rate limiter"
```

---

### Task 2: Add `RateLimiter` and global registry with tests

**Files:**
- Modify: `src/everstaff/llm/rate_limiter.py`
- Modify: `tests/test_llm/test_rate_limiter.py`

- [ ] **Step 1: Write failing tests for RateLimiter and registry**

Append to `tests/test_llm/test_rate_limiter.py`:

```python
@pytest.mark.asyncio
async def test_rate_limiter_no_limits():
    """RateLimiter with no limits should not block."""
    from everstaff.llm.rate_limiter import RateLimiter

    rl = RateLimiter()
    start = time.monotonic()
    for _ in range(100):
        await rl.before_request()
        await rl.after_request(1000)
    elapsed = time.monotonic() - start
    assert elapsed < 0.5  # no blocking


@pytest.mark.asyncio
async def test_rate_limiter_rpm_throttles():
    """RateLimiter with rpm_limit should throttle requests."""
    from everstaff.llm.rate_limiter import RateLimiter

    rl = RateLimiter(rpm_limit=60)  # 1 req/sec
    await rl.before_request()  # first: immediate
    await rl.before_request()  # second: should wait ~1s? No — bucket starts full at 60
    # Drain bucket
    for _ in range(58):
        await rl.before_request()
    # Now bucket is at 0, next should wait
    start = time.monotonic()
    await rl.before_request()
    elapsed = time.monotonic() - start
    assert elapsed > 0.5  # had to wait for refill


@pytest.mark.asyncio
async def test_rate_limiter_tpm_throttles_after_consume():
    """RateLimiter TPM should throttle after large token consumption."""
    from everstaff.llm.rate_limiter import RateLimiter

    rl = RateLimiter(tpm_limit=1000)  # 1000 tokens/min
    await rl.before_request()  # immediate (bucket full)
    await rl.after_request(1500)  # consume 1500 → bucket at -500
    start = time.monotonic()
    await rl.before_request()  # must wait for bucket to reach 0
    elapsed = time.monotonic() - start
    assert elapsed > 0.1  # had to wait


def test_registry_returns_same_instance():
    """get_rate_limiter should return the same instance for same model_id."""
    from everstaff.llm.rate_limiter import get_rate_limiter, _registry

    _registry.clear()
    rl1 = get_rate_limiter("model-a", tpm_limit=1000, rpm_limit=10)
    rl2 = get_rate_limiter("model-a", tpm_limit=1000, rpm_limit=10)
    assert rl1 is rl2
    _registry.clear()


def test_registry_different_models():
    """Different model_ids should get different instances."""
    from everstaff.llm.rate_limiter import get_rate_limiter, _registry

    _registry.clear()
    rl1 = get_rate_limiter("model-a", tpm_limit=1000)
    rl2 = get_rate_limiter("model-b", tpm_limit=2000)
    assert rl1 is not rl2
    _registry.clear()


def test_registry_warns_on_conflicting_limits(caplog):
    """get_rate_limiter should warn if limits differ for same model_id."""
    import logging
    from everstaff.llm.rate_limiter import get_rate_limiter, _registry

    _registry.clear()
    get_rate_limiter("model-x", tpm_limit=1000)
    with caplog.at_level(logging.WARNING):
        get_rate_limiter("model-x", tpm_limit=9999)
    assert "conflicting" in caplog.text.lower() or "mismatch" in caplog.text.lower()
    _registry.clear()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /Users/bytedance/Projects/cyber_yuri/everstaff && uv run pytest tests/test_llm/test_rate_limiter.py -v -k "rate_limiter or registry"`
Expected: FAIL — `ImportError: cannot import name 'RateLimiter'`

- [ ] **Step 3: Implement RateLimiter and registry**

Append to `src/everstaff/llm/rate_limiter.py`:

```python
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


# ---------------------------------------------------------------------------
# Global registry — all LiteLLMClient instances sharing a model_id share
# one RateLimiter so they collectively respect the endpoint quota.
# ---------------------------------------------------------------------------
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /Users/bytedance/Projects/cyber_yuri/everstaff && uv run pytest tests/test_llm/test_rate_limiter.py -v`
Expected: All tests PASS

- [ ] **Step 5: Commit**

```bash
cd /Users/bytedance/Projects/cyber_yuri/everstaff
git add src/everstaff/llm/rate_limiter.py tests/test_llm/test_rate_limiter.py
git commit -m "feat: add RateLimiter with TPM/RPM buckets and global registry"
```

---

## Chunk 2: Schema + LiteLLMClient Integration

### Task 3: Add `tpm_limit` and `rpm_limit` to ModelMapping

**Files:**
- Modify: `src/everstaff/schema/model_config.py:8-19`

- [ ] **Step 1: Add fields to ModelMapping**

Add two fields at the end of the `ModelMapping` class in `src/everstaff/schema/model_config.py`:

```python
    stream_total_timeout: int = 600  # total wall-clock seconds for the entire streaming call
    tpm_limit: int | None = None     # tokens per minute limit; None = unlimited
    rpm_limit: int | None = None     # requests per minute limit; None = unlimited
```

- [ ] **Step 2: Verify schema loads correctly**

Run: `cd /Users/bytedance/Projects/cyber_yuri/everstaff && uv run python -c "from everstaff.schema.model_config import ModelMapping; m = ModelMapping(model_id='test'); print(m.tpm_limit, m.rpm_limit)"`
Expected: `None None`

- [ ] **Step 3: Commit**

```bash
cd /Users/bytedance/Projects/cyber_yuri/everstaff
git add src/everstaff/schema/model_config.py
git commit -m "feat: add tpm_limit and rpm_limit to ModelMapping schema"
```

---

### Task 4: Integrate rate limiter into LiteLLMClient

**Files:**
- Modify: `src/everstaff/llm/litellm_client.py:1-10` (imports)
- Modify: `src/everstaff/llm/litellm_client.py:255-266` (`__init__`)
- Modify: `src/everstaff/llm/litellm_client.py:273-361` (`complete()`)
- Modify: `src/everstaff/llm/litellm_client.py:363-543` (`complete_stream()`)

- [ ] **Step 1: Add imports**

Add to the imports section at the top of `src/everstaff/llm/litellm_client.py`:

```python
import random
```

- [ ] **Step 2: Modify `__init__` to set up rate limiter**

Replace the current `__init__` (lines 256-266) with:

```python
    def __init__(self, model: str, **kwargs: Any) -> None:
        self._model = model
        self._stream_chunk_timeout: int | None = kwargs.pop("stream_chunk_timeout", None)
        _request_timeout = kwargs.get("timeout") or 120
        self._stream_total_timeout: int = kwargs.pop(
            "stream_total_timeout", _request_timeout * 5
        )
        # Rate limiting — pop our custom keys before forwarding to litellm
        _tpm_limit: int | None = kwargs.pop("tpm_limit", None)
        _rpm_limit: int | None = kwargs.pop("rpm_limit", None)
        from everstaff.llm.rate_limiter import get_rate_limiter
        self._rate_limiter = get_rate_limiter(model, tpm_limit=_tpm_limit, rpm_limit=_rpm_limit)
        # Take over retry control — disable litellm's built-in retry so our
        # retry loop can re-acquire from the rate limiter before each attempt.
        self._max_retries: int = kwargs.pop("num_retries", 2)
        self._kwargs = kwargs
```

- [ ] **Step 3: Modify `complete()` to add rate limiting + 429 retry**

Replace the `complete` method body. The method signature stays the same. Replace lines 273-361 with:

```python
    async def complete(
        self,
        messages: list[Message],
        tools: list[ToolDefinition],
        system: str | None = None,
    ) -> LLMResponse:
        msgs: list[dict[str, Any]] = []
        if system:
            msgs.append({"role": "system", "content": system})
        msgs.extend(m.to_dict() for m in messages)

        litellm_tools = [
            {
                "type": "function",
                "function": {
                    "name": t.name,
                    "description": t.description,
                    "parameters": _params_to_json_schema(t),
                },
            }
            for t in tools
        ] or None

        last_exc: Exception | None = None
        for attempt in range(self._max_retries + 1):
            await self._rate_limiter.before_request()
            try:
                response = await litellm.acompletion(
                    model=self._model,
                    messages=msgs,
                    tools=litellm_tools,
                    **self._kwargs,
                )
            except Exception as exc:
                if _is_rate_limit_error(exc) and attempt < self._max_retries:
                    delay = min(2 ** attempt, 30) * random.uniform(0.5, 1.5)
                    logger.warning(
                        "429 rate limited (model=%s), retry %d/%d in %.1fs: %s",
                        self._model, attempt + 1, self._max_retries, delay, exc,
                    )
                    last_exc = exc
                    await asyncio.sleep(delay)
                    continue
                raise
            # Deduct actual tokens from bucket
            usage = getattr(response, "usage", None)
            input_tokens = int(getattr(usage, "prompt_tokens", 0) or 0)
            output_tokens = int(getattr(usage, "completion_tokens", 0) or 0)
            await self._rate_limiter.after_request(input_tokens + output_tokens)

            choice = response.choices[0]
            finish_reason = getattr(choice, "finish_reason", None)
            msg = choice.message
            tool_calls: list[ToolCallRequest] = []

            if msg.tool_calls:
                for tc in msg.tool_calls:
                    try:
                        args = json.loads(tc.function.arguments)
                    except (json.JSONDecodeError, TypeError):
                        try:
                            args = ast.literal_eval(tc.function.arguments)
                        except Exception:
                            args = {}
                    tool_calls.append(ToolCallRequest(
                        id=tc.id,
                        name=tc.function.name,
                        args=args,
                    ))

            content = msg.content
            if not tool_calls and content and litellm_tools:
                xml_calls, cleaned_content = _parse_xml_tool_calls(content)
                if xml_calls:
                    logger.warning(
                        "Model %s returned %d tool call(s) as XML in content; "
                        "using fallback parser",
                        self._model, len(xml_calls),
                    )
                    tool_calls = xml_calls
                    content = cleaned_content or None

            thinking: str | None = getattr(msg, "thinking", None)
            if not thinking:
                thinking = getattr(msg, "reasoning_content", None) or None
            if not thinking and content:
                extracted_thinking, content = _extract_think_tags(content)
                if extracted_thinking:
                    thinking = extracted_thinking
                    content = content or None

            return LLMResponse(
                content=content,
                tool_calls=tool_calls,
                thinking=thinking,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                finish_reason=finish_reason,
            )

        # Should not reach here, but just in case
        raise last_exc or RuntimeError("Rate limit retries exhausted")
```

- [ ] **Step 4: Modify `complete_stream()` to add rate limiting + 429 retry**

Wrap the existing `complete_stream()` body with rate limiting. Replace lines 363 onwards. The key changes:
1. Wrap in a `for attempt in range(...)` retry loop
2. `await self._rate_limiter.before_request()` before `litellm.acompletion(stream=True)`
3. `await self._rate_limiter.after_request(input_tokens + output_tokens)` in the final `yield ("done", ...)` section
4. Catch `_is_rate_limit_error` around the `acompletion` call and early chunk reads

```python
    async def complete_stream(
        self,
        messages: list[Message],
        tools: list[ToolDefinition],
        system: str | None = None,
    ):
        msgs: list[dict[str, Any]] = []
        if system:
            msgs.append({"role": "system", "content": system})
        msgs.extend(m.to_dict() for m in messages)

        litellm_tools = [
            {
                "type": "function",
                "function": {
                    "name": t.name,
                    "description": t.description,
                    "parameters": _params_to_json_schema(t),
                },
            }
            for t in tools
        ] or None

        last_exc: Exception | None = None
        for attempt in range(self._max_retries + 1):
            await self._rate_limiter.before_request()
            try:
                stream = await litellm.acompletion(
                    model=self._model,
                    messages=msgs,
                    tools=litellm_tools,
                    stream=True,
                    stream_options={"include_usage": True},
                    **self._kwargs,
                )
            except Exception as exc:
                if _is_rate_limit_error(exc) and attempt < self._max_retries:
                    delay = min(2 ** attempt, 30) * random.uniform(0.5, 1.5)
                    logger.warning(
                        "429 rate limited on stream init (model=%s), retry %d/%d in %.1fs",
                        self._model, attempt + 1, self._max_retries, delay,
                    )
                    last_exc = exc
                    await asyncio.sleep(delay)
                    continue
                raise

            # Stream opened successfully — process chunks (no retry mid-stream)
            full_content: list[str] = []
            thinking_chunks: list[str] = []
            tool_calls_acc: dict[int, dict] = {}
            input_tokens = 0
            output_tokens = 0
            finish_reason: str | None = None

            parser = _ThinkTagStreamParser()
            repetition_detector = _RepetitionDetector()

            _chunk_timeout = self._stream_chunk_timeout
            _total_timeout = self._stream_total_timeout
            _stream_start = time.monotonic()
            _SENTINEL = object()
            _aiter = stream.__aiter__()
            while True:
                _elapsed = time.monotonic() - _stream_start
                if _total_timeout and _elapsed > _total_timeout:
                    raise TimeoutError(
                        f"LLM streaming total timeout: {_elapsed:.0f}s exceeded "
                        f"{_total_timeout}s limit (model={self._model})"
                    )
                try:
                    chunk = await asyncio.wait_for(
                        anext(_aiter, _SENTINEL),
                        timeout=_chunk_timeout,
                    )
                except asyncio.TimeoutError:
                    raise TimeoutError(
                        f"LLM streaming stalled: no chunk received for "
                        f"{_chunk_timeout}s (model={self._model})"
                    ) from None
                if chunk is _SENTINEL:
                    break

                delta = chunk.choices[0].delta

                _repetition_hit = False
                if delta.content:
                    for kind, text in parser.feed(delta.content):
                        if kind == "thinking":
                            thinking_chunks.append(text)
                            yield ("thinking", text)
                            if repetition_detector.feed(text):
                                _repetition_hit = True
                        else:
                            full_content.append(text)
                            yield ("text", text)

                thinking_chunk = getattr(delta, "thinking", None) or getattr(delta, "reasoning_content", None)
                if thinking_chunk:
                    thinking_chunks.append(thinking_chunk)
                    yield ("thinking", thinking_chunk)
                    if repetition_detector.feed(thinking_chunk):
                        _repetition_hit = True

                if _repetition_hit:
                    logger.warning(
                        "Repetition loop detected in LLM streaming output "
                        "(model=%s) — aborting stream early",
                        self._model,
                    )
                    finish_reason = "repetition_detected"
                    break

                if delta.tool_calls:
                    for tc_chunk in delta.tool_calls:
                        idx = tc_chunk.index
                        if idx not in tool_calls_acc:
                            tool_calls_acc[idx] = {"id": "", "name": "", "args_str": ""}
                        if tc_chunk.id:
                            tool_calls_acc[idx]["id"] = tc_chunk.id
                        fn = tc_chunk.function
                        if getattr(fn, "name", None):
                            tool_calls_acc[idx]["name"] += fn.name
                        if getattr(fn, "arguments", None):
                            tool_calls_acc[idx]["args_str"] += fn.arguments

                _fr = getattr(chunk.choices[0], "finish_reason", None)
                if _fr:
                    finish_reason = _fr

                usage = getattr(chunk, "usage", None)
                if usage:
                    input_tokens = int(getattr(usage, "prompt_tokens", 0) or 0)
                    output_tokens = int(getattr(usage, "completion_tokens", 0) or 0)

            for kind, text in parser.flush():
                if kind == "thinking":
                    thinking_chunks.append(text)
                    yield ("thinking", text)
                else:
                    full_content.append(text)
                    yield ("text", text)

            tool_calls: list[ToolCallRequest] = []
            for idx in sorted(tool_calls_acc):
                tc = tool_calls_acc[idx]
                try:
                    args = json.loads(tc["args_str"])
                except (json.JSONDecodeError, ValueError):
                    try:
                        args = ast.literal_eval(tc["args_str"])
                    except Exception:
                        args = {}
                tool_calls.append(ToolCallRequest(id=tc["id"], name=tc["name"], args=args))

            content = "".join(full_content) or None
            thinking = "".join(thinking_chunks) or None

            if not tool_calls and content and litellm_tools:
                xml_calls, cleaned_content = _parse_xml_tool_calls(content)
                if xml_calls:
                    logger.warning(
                        "Model %s returned %d tool call(s) as XML in content (streaming); using fallback parser",
                        self._model, len(xml_calls),
                    )
                    tool_calls = xml_calls
                    content = cleaned_content or None

            # Deduct actual tokens from rate limiter
            await self._rate_limiter.after_request(input_tokens + output_tokens)

            yield ("done", LLMResponse(
                content=content,
                tool_calls=tool_calls,
                thinking=thinking,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                finish_reason=finish_reason,
            ))
            return  # success — exit retry loop

        # All retries exhausted on stream init
        raise last_exc or RuntimeError("Rate limit retries exhausted")
```

- [ ] **Step 5: Add `_is_rate_limit_error` helper**

Add this module-level function near the top of `litellm_client.py`, after the existing imports:

```python
def _is_rate_limit_error(exc: Exception) -> bool:
    """Check if an exception is a rate limit (429) error."""
    # litellm raises various exception types for 429
    exc_type = type(exc).__name__
    if "RateLimit" in exc_type:
        return True
    # Check for status_code attribute (litellm exceptions)
    status = getattr(exc, "status_code", None)
    if status == 429:
        return True
    # Check string representation as last resort
    msg = str(exc).lower()
    return "429" in msg or "rate limit" in msg or "too many requests" in msg
```

- [ ] **Step 6: Run existing LLM tests to verify no regression**

Run: `cd /Users/bytedance/Projects/cyber_yuri/everstaff && uv run pytest tests/test_llm/ -v`
Expected: All tests PASS

- [ ] **Step 7: Commit**

```bash
cd /Users/bytedance/Projects/cyber_yuri/everstaff
git add src/everstaff/llm/litellm_client.py
git commit -m "feat: integrate rate limiter + 429 retry into LiteLLMClient"
```

---

## Chunk 3: Wiring + Config

### Task 5: Wire rate limit config through AgentBuilder and daemon factory

**Files:**
- Modify: `src/everstaff/builder/agent_builder.py:315-324`
- Modify: `src/everstaff/api/__init__.py:67-79`

- [ ] **Step 1: Add tpm/rpm to AgentBuilder LLM kwargs**

In `src/everstaff/builder/agent_builder.py`, after line 324 (`llm_kwargs["stream_total_timeout"] = mapping.stream_total_timeout`), add:

```python
        llm_kwargs["tpm_limit"] = mapping.tpm_limit
        llm_kwargs["rpm_limit"] = mapping.rpm_limit
```

- [ ] **Step 2: Add tpm/rpm to daemon factory**

In `src/everstaff/api/__init__.py`, modify `_daemon_llm_factory` (lines 71-79) to include rate limit params:

```python
                    return LiteLLMClient(
                        model=mapping.model_id,
                        max_tokens=mapping.max_output_tokens,
                        temperature=mapping.temperature,
                        timeout=mapping.timeout,
                        num_retries=mapping.max_retries,
                        stream_chunk_timeout=mapping.stream_chunk_timeout,
                        stream_total_timeout=mapping.stream_total_timeout,
                        tpm_limit=mapping.tpm_limit,
                        rpm_limit=mapping.rpm_limit,
                    )
```

- [ ] **Step 3: Commit**

```bash
cd /Users/bytedance/Projects/cyber_yuri/everstaff
git add src/everstaff/builder/agent_builder.py src/everstaff/api/__init__.py
git commit -m "feat: wire tpm_limit and rpm_limit through builder and daemon factory"
```

---

### Task 6: Update project config

**Files:**
- Modify: `.agent/config.yaml:38-65`

- [ ] **Step 1: Add tpm_limit and rpm_limit to config.yaml model mappings**

Add `tpm_limit` and `rpm_limit` to each model mapping in `/Users/bytedance/Projects/cyber_yuri/.agent/config.yaml`. Example for the `smart` mapping:

```yaml
  smart:
    model_id: "openai/ep-20260225153025-5t9rd"
    max_tokens: 256000
    max_output_tokens: 8192
    temperature: 0.7
    supports_tools: true
    timeout: 120
    max_retries: 3
    tpm_limit: 200000
    rpm_limit: 60
```

Apply similar values to `fast` and `reasoning` mappings. Adjust the actual TPM/RPM numbers based on your endpoint quotas.

- [ ] **Step 2: Verify config loads**

Run: `cd /Users/bytedance/Projects/cyber_yuri/everstaff && uv run python -c "from everstaff.core.config import load_config; c = load_config('/Users/bytedance/Projects/cyber_yuri'); m = c.resolve_model('smart'); print(f'tpm={m.tpm_limit} rpm={m.rpm_limit}')"`
Expected: `tpm=200000 rpm=60`

- [ ] **Step 3: Commit**

```bash
cd /Users/bytedance/Projects/cyber_yuri
git add .agent/config.yaml
git commit -m "config: add tpm_limit and rpm_limit to model mappings"
```
