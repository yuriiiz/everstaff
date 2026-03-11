# LLM Rate Limiting Design

## Problem

Concurrent agent sessions (workflow sub-agents, daemon loops, memory operations) share the same Ark API endpoints. Each endpoint has independent TPM/RPM quotas. Without rate limiting, burst traffic triggers 429 errors and failed requests.

## Solution

Three-layer rate limiting at the LLM client level:

1. **RPM token bucket** — gates requests before sending
2. **TPM token bucket** — tracks actual token consumption, throttles when budget exhausted
3. **429 backoff retry** — catches rate limit errors that slip through, retries with exponential backoff + jitter

## Execution Flow

```
Request cycle:
  1. await rpm_bucket.acquire(1)          # wait if RPM exhausted
  2. await tpm_bucket.acquire(0)          # wait if TPM bucket negative (no pre-deduction)
  3. send LLM request (with num_retries=0 — litellm built-in retry disabled)
  4. on success: tpm_bucket.consume(input_tokens + output_tokens)
  5. on 429:     sleep(base_delay * 2^attempt * jitter) → goto 1
  6. on max_retries exceeded: raise
```

## Configuration

New fields in `ModelMapping` (`schema/model_config.py`):

```python
tpm_limit: int | None = None   # tokens per minute; None = unlimited
rpm_limit: int | None = None   # requests per minute; None = unlimited
```

Example `config.yaml`:

```yaml
model_mappings:
  smart:
    model_id: "openai/ep-20260225153025-5t9rd"
    max_tokens: 256000
    max_output_tokens: 8192
    tpm_limit: 200000
    rpm_limit: 60
    max_retries: 3
```

## Components

### `llm/rate_limiter.py` (new file)

#### `TokenBucket`

Generic async token bucket. Used for both TPM and RPM.

```python
class TokenBucket:
    def __init__(self, capacity: float, refill_rate: float):
        """
        capacity: max tokens in bucket (= TPM or RPM limit)
        refill_rate: tokens added per second (= capacity / 60)
        """
        self._capacity = capacity
        self._tokens = capacity       # start full
        self._refill_rate = refill_rate
        self._last_refill = time.monotonic()
        self._lock = asyncio.Lock()

    def _refill(self) -> None:
        """Add tokens based on elapsed time since last refill. No-lock, caller holds lock."""
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
                # Calculate wait time for enough tokens to accumulate
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

Key behaviors:
- `acquire()` releases the lock during sleep so concurrent coroutines are not blocked
- `consume()` is async and holds the lock to prevent data races
- Bucket can go negative after `consume()` — this naturally throttles subsequent `acquire()` calls
- Refill is calculated lazily on each access using elapsed time, not a background timer

#### `RateLimiter`

Composes TPM + RPM buckets for one model endpoint.

```python
class RateLimiter:
    def __init__(self, tpm_limit: int | None = None, rpm_limit: int | None = None):
        self._tpm = TokenBucket(tpm_limit, tpm_limit / 60) if tpm_limit else None
        self._rpm = TokenBucket(rpm_limit, rpm_limit / 60) if rpm_limit else None

    async def before_request(self) -> None:
        """Await both RPM and TPM budgets before sending."""
        if self._rpm:
            await self._rpm.acquire(1)
        if self._tpm:
            await self._tpm.acquire(0)  # just wait for non-negative, no pre-deduction

    async def after_request(self, tokens_used: int) -> None:
        """Record actual token consumption."""
        if self._tpm and tokens_used > 0:
            await self._tpm.consume(tokens_used)
```

#### Global Registry

```python
_registry: dict[str, RateLimiter] = {}

def get_rate_limiter(
    model_id: str,
    tpm_limit: int | None = None,
    rpm_limit: int | None = None,
) -> RateLimiter:
    """Get or create a RateLimiter for the given model_id.

    If a limiter already exists for this model_id but with different limits,
    log a warning and return the existing limiter (first-registered wins).
    """
```

All LiteLLMClient instances sharing the same `model_id` share one RateLimiter. The registry is process-global. No lock is needed because all initialization runs on the same event loop thread.

### `llm/litellm_client.py` (modified)

Changes to `__init__`:
- Pop `tpm_limit` and `rpm_limit` from kwargs
- Obtain shared `RateLimiter` from registry via `get_rate_limiter(model, tpm_limit, rpm_limit)`
- Pop `num_retries` from kwargs into `self._max_retries` (default 2) — **litellm's built-in retry is disabled** to avoid double-retry; our retry loop re-acquires from the rate limiter bucket before each attempt

Changes to `complete()`:
```python
async def complete(self, messages, tools, system=None):
    for attempt in range(self._max_retries + 1):
        await self._rate_limiter.before_request()
        try:
            response = await litellm.acompletion(...)  # num_retries NOT in kwargs
            tokens = (response.usage.prompt_tokens or 0) + (response.usage.completion_tokens or 0)
            await self._rate_limiter.after_request(tokens)
            return self._parse_response(response)
        except litellm.RateLimitError as exc:
            if attempt >= self._max_retries:
                raise
            delay = min(2 ** attempt, 30) * random.uniform(0.5, 1.5)  # jitter
            logger.warning(
                "429 rate limited (model=%s), retry %d/%d in %.1fs: %s",
                self._model, attempt + 1, self._max_retries, delay, exc,
            )
            await asyncio.sleep(delay)
```

Changes to `complete_stream()`:
- Same `before_request()` gate before `litellm.acompletion(stream=True)`
- `after_request(input_tokens + output_tokens)` after stream completes (tokens from final usage chunk)
- Same 429 retry loop wrapping the entire stream
- **Streaming usage fallback:** if the provider does not include usage in the streaming response (common), `after_request(0)` is called. This means TPM limiting is best-effort for streaming — acknowledged limitation. RPM limiting still works.

### `schema/model_config.py` (modified)

```python
class ModelMapping(BaseModel):
    # ... existing fields ...
    tpm_limit: int | None = None
    rpm_limit: int | None = None
```

### `builder/agent_builder.py` (modified)

Pass `tpm_limit` and `rpm_limit` to LiteLLMClient constructor:
```python
llm_kwargs["tpm_limit"] = mapping.tpm_limit
llm_kwargs["rpm_limit"] = mapping.rpm_limit
```

### `api/__init__.py` (modified)

Update `_daemon_llm_factory` to pass `tpm_limit` and `rpm_limit`.

## Design Decisions

**Why disable litellm's built-in `num_retries` and use our own retry loop?**
litellm's built-in retry on 429 does exponential backoff but does NOT re-acquire from our rate limiter bucket before retrying. Our manual loop ensures each retry attempt goes through `before_request()` first, so retries respect the shared rate limit rather than blindly hammering the API.

**Why post-deduction for TPM (not pre-deduction)?**
We don't know token count before the request. Pre-estimation (chars/4) is unreliable. Post-deduction with negative bucket naturally throttles subsequent requests.

**Why global registry instead of per-client bucket?**
Workflow sub-agents and daemon loops each create independent LiteLLMClient instances. They all share the same endpoint quota, so they must share the same bucket.

**Why lazy refill instead of background timer?**
Simpler, no background tasks to manage, no cleanup needed. Refill is calculated as `elapsed_seconds * refill_rate` on each access.

**Why jitter on backoff?**
When multiple agents hit 429 simultaneously (thundering herd), pure exponential backoff causes them all to retry at the same instant. Jitter (`* random.uniform(0.5, 1.5)`) spreads retries and reduces contention.

**Why cap backoff at 30s?**
Ark API rate limits typically reset within a minute. Longer waits are counterproductive.

**Conflicting limits for same model_id:**
The registry uses first-registered-wins. If a second registration arrives with different `tpm_limit`/`rpm_limit` for the same `model_id`, a warning is logged and the existing limiter is returned. In practice all agents using the same endpoint should have the same limits (set once in `model_mappings`).

**Sandbox processes:**
Sandbox processes run in separate OS processes with their own global registry. Rate limiting is per-process only. Cross-process rate limiting is out of scope.

## Files Changed

| File | Change |
|------|--------|
| `llm/rate_limiter.py` | New — TokenBucket, RateLimiter, global registry |
| `schema/model_config.py` | Add `tpm_limit`, `rpm_limit` fields |
| `llm/litellm_client.py` | Integrate rate limiter + 429 retry loop, disable litellm built-in retry |
| `builder/agent_builder.py` | Forward tpm/rpm config to LLM client |
| `api/__init__.py` | Forward tpm/rpm in daemon factory |
| `.agent/config.yaml` | Add tpm_limit/rpm_limit to model mappings |
