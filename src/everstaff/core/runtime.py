"""AgentRuntime — thin conversation loop with full lifecycle tracing and cancellation."""
from __future__ import annotations

import asyncio
import json
import logging
import time
from collections.abc import AsyncIterator
from datetime import datetime, timezone

from pathlib import Path

from everstaff.core.context import AgentContext
from everstaff.session.index import SessionIndex as _SI
from everstaff.tools.pipeline import ToolCallContext
from everstaff.protocols import HumanApprovalRequired, LLMClient, Message, TraceEvent
from everstaff.utils.workspace_diff import snapshot_workspace, diff_snapshots, guess_mime
from everstaff.schema.token_stats import SessionStats, TokenUsage
from everstaff.schema.stream import (
    StreamEvent,
    TextDelta,
    ThinkingDelta,
    ToolCallStart,
    ToolCallEnd,
    TurnStart,
    SessionEnd,
    ErrorEvent,
    HitlRequestEvent,
    FileCreatedEvent,
)

logger = logging.getLogger(__name__)

_STOPPED = "[Stopped]"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _drop_dangling_tool_calls(messages: "list[Message]") -> "list[Message]":
    """Fix trailing assistant message(s) whose tool_calls have no matching tool results.

    When a session is saved mid-execution (after the LLM emitted tool_calls but
    before all tool results were appended), the history may contain an assistant
    message with partially or fully unresolved tool_calls.  This can happen when:

    1. The session was saved before all tool results were appended (no tool results
       follow the assistant message).
    2. HITL interrupted a multi-tool-call batch: some tool calls completed, HITL
       resolved one, but remaining calls were never executed.  The assistant
       message references N tool_calls but only M < N results exist.

    Sending such messages to the LLM violates the OpenAI/Anthropic protocol.

    This function handles both cases:
    - Fully unresolved: drops the trailing assistant message entirely.
    - Partially resolved: injects error tool-result messages for unfulfilled calls
      so the LLM can see what happened and decide whether to retry.
    """
    if not messages:
        return messages

    # Collect the tool_call ids that have matching tool results
    fulfilled: set[str] = set()
    for m in messages:
        if m.role == "tool" and m.tool_call_id:
            fulfilled.add(m.tool_call_id)

    result = list(messages)

    # Phase 1: Drop trailing assistant messages with zero fulfilled tool calls.
    while result:
        last = result[-1]
        if last.role == "assistant" and last.tool_calls:
            call_ids = {tc["id"] for tc in last.tool_calls if isinstance(tc, dict) and "id" in tc}
            if not call_ids or not call_ids.issubset(fulfilled):
                if not (call_ids & fulfilled):
                    # Fully unresolved — drop the assistant message
                    logger.warning(
                        "Dropping dangling assistant+tool_calls from history "
                        "(session was saved before tool results were appended). "
                        "Affected call IDs: %s",
                        call_ids - fulfilled,
                    )
                    result.pop()
                    continue
        break

    # Phase 2: Handle partially fulfilled tool calls.
    # Walk backward to find the last assistant message with tool_calls.
    # For unfulfilled calls, inject synthetic error tool-result messages
    # so the protocol is satisfied and the LLM knows which calls were skipped.
    for i in range(len(result) - 1, -1, -1):
        msg = result[i]
        if msg.role == "assistant" and msg.tool_calls:
            call_ids = {tc["id"] for tc in msg.tool_calls if isinstance(tc, dict) and "id" in tc}
            unfulfilled = call_ids - fulfilled
            if unfulfilled:
                logger.warning(
                    "Injecting error results for %d unfulfilled tool call(s) "
                    "out of %d total. Unfulfilled IDs: %s",
                    len(unfulfilled), len(call_ids), unfulfilled,
                )
                # Inject a synthetic error tool result for each unfulfilled call
                for tc in msg.tool_calls:
                    if isinstance(tc, dict) and tc.get("id") in unfulfilled:
                        result.append(Message(
                            role="tool",
                            content="[Tool call was not executed: session was interrupted before this call could run. You may retry if needed.]",
                            tool_call_id=tc["id"],
                            created_at=datetime.now(timezone.utc).isoformat(),
                        ))
            break  # only fix the last assistant+tool_calls turn
        elif msg.role not in ("tool",):
            break  # stop scanning if we hit a non-tool message

    return result


class AgentRuntime:
    def __init__(self, context: AgentContext, llm_client: LLMClient) -> None:
        self._ctx = context
        self._llm = llm_client
        self._current_span_id: str | None = None
        self.stats: "SessionStats | None" = None  # populated after run() completes
        self._pending_child_hitls: list = []  # HitlRequest objects from child sub-agents

    def _hook_ctx(self) -> "HookContext":
        from everstaff.protocols import HookContext
        return HookContext(session_id=self._ctx.session_id, agent_name=self._ctx.agent_name)

    async def _hook(self, method: str, value, *args):
        """Mutable hook — each hook receives previous output."""
        ctx = self._hook_ctx()
        for hook in self._ctx.hooks:
            try:
                value = await getattr(hook, method)(ctx, value, *args)
            except Exception as e:
                logger.warning("Hook %s.%s raised: %s", type(hook).__name__, method, e)
        return value

    async def _hook_notify(self, method: str, *args):
        """Non-mutable hook — fire and forget."""
        ctx = self._hook_ctx()
        for hook in self._ctx.hooks:
            try:
                await getattr(hook, method)(ctx, *args)
            except Exception as e:
                logger.warning("Hook %s.%s raised: %s", type(hook).__name__, method, e)

    async def _save_session(self, session_id: str, messages: list[Message], **kwargs) -> None:
        """Wrapper around memory.save() that injects root_session_id."""
        kwargs.setdefault("root_session_id", self._ctx.root_session_id)
        await self._ctx.memory.save(session_id, messages, **kwargs)

    async def _is_cancelled(self) -> bool:
        """Check cancellation: file signal (stateless) or in-process flag."""
        if self._ctx.cancellation.is_cancelled:
            return True
        store = self._ctx.file_store
        if store is not None:
            signal_path = _SI.signal_relpath(self._ctx.session_id, self._ctx.root_session_id)
            try:
                return await store.exists(signal_path)
            except Exception:
                pass
        return False

    def _emit(self, kind: str, data: dict, duration_ms: float | None = None) -> None:
        event = TraceEvent(
            kind=kind,
            session_id=self._ctx.session_id,
            parent_session_id=self._ctx.parent_session_id,
            timestamp=_now(),
            duration_ms=duration_ms,
            data=data,
            parent_span_id=(
                self._ctx.caller_span_id if kind == "session_start"
                else self._current_span_id
            ),
        )
        self._current_span_id = event.span_id
        self._ctx.tracer.on_event(event)

    def _build_system_prompt(self) -> str | None:
        ctx = self._ctx
        parts = []
        if ctx.system_prompt:
            parts.append(ctx.system_prompt)
        for provider in [ctx.skill_provider, ctx.knowledge_provider,
                         ctx.sub_agent_provider, ctx.mcp_provider]:
            injection = provider.get_prompt_injection()
            if injection:
                parts.append(injection)
        # Conditional HITL rules: inject when request_human_input is available
        if ctx.tool_registry.has_tool("request_human_input"):
            from everstaff.tools.hitl_tool import RequestHumanInputTool
            hitl_tool = ctx.tool_registry._tools.get("request_human_input")
            if isinstance(hitl_tool, RequestHumanInputTool):
                parts.append(hitl_tool.get_prompt_injection())
        result = "\n\n".join(parts).strip()
        return result if result else None


    async def _generate_title(self, user_input: str, first_reply: str) -> None:
        """Fire-and-forget: generate a session title from first exchange."""
        try:
            prompt = (
                "Summarize the topic of this conversation in one short phrase "
                "(5 words max, no punctuation, title case):\n"
                f"User: {user_input[:500]}\n"
                f"Assistant: {first_reply[:500]}"
            )
            messages = [Message(role="user", content=prompt, created_at=datetime.now(timezone.utc).isoformat())]
            t0 = time.monotonic()
            self._emit("llm_start", {
                "purpose": "title_generation",
                "message_count": 1,
                "messages": [m.to_dict() for m in messages],
            })
            messages = await self._hook("on_llm_start", messages)
            response = await self._llm.complete(
                messages=messages,
                tools=[],
                system=None,
            )
            response = await self._hook("on_llm_end", response)
            llm_ms = (time.monotonic() - t0) * 1000
            self._emit("llm_end", {
                "purpose": "title_generation",
                "content": response.content,
                "input_tokens": response.input_tokens,
                "output_tokens": response.output_tokens,
            }, duration_ms=llm_ms)
            title = (response.content or "").strip()
            if title:
                existing_messages = await self._ctx.memory.load(self._ctx.session_id)
                await self._save_session(
                    self._ctx.session_id,
                    existing_messages,
                    agent_name=self._ctx.agent_name,
                    agent_uuid=self._ctx.agent_uuid,
                    title=title,
                )
        except Exception as e:
            logger.debug("Title generation failed: %s", e)

    async def run_stream(self, user_input: "str | None") -> AsyncIterator[StreamEvent]:
        """Primary execution path — yields StreamEvent objects in real time.

        Pass user_input=None for HITL resume where the decision has already been
        inserted into memory as a tool message; no new user message will be appended.
        """
        try:
            async for event in self._run_stream_inner(user_input):
                yield event
        finally:
            if hasattr(self._ctx.tracer, "aflush"):
                await self._ctx.tracer.aflush()

    async def _run_stream_inner(self, user_input: "str | None") -> AsyncIterator[StreamEvent]:
        """Inner implementation of run_stream — all exit paths are covered by run_stream's finally."""
        session_start = time.monotonic()
        self._emit("session_start", {"agent_name": self._ctx.agent_name})
        await self._hook_notify("on_session_start")
        # Load existing messages before creating the stub so we don't overwrite them
        messages = await self._ctx.memory.load(self._ctx.session_id)
        # Create session file immediately so it's visible during execution
        await self._save_session(
            self._ctx.session_id,
            messages,
            agent_name=self._ctx.agent_name,
            agent_uuid=self._ctx.agent_uuid,
            parent_session_id=self._ctx.parent_session_id,
            status="running",
            max_tokens=self._ctx.max_tokens,
            trigger=self._ctx.trigger,
        )
        self._emit("user_input", {"content": user_input or ""})
        if user_input is not None:
            user_input = await self._hook("on_user_input", user_input)

        # Load existing stats to accumulate across HITL resumes.
        # Without this, each resume starts with fresh stats and tool_calls_count resets.
        existing_stats: "SessionStats | None" = None
        _load_stats_fn = getattr(self._ctx.memory, "load_stats", None)
        if _load_stats_fn is not None:
            existing_stats = await _load_stats_fn(self._ctx.session_id)
        stats = existing_stats if existing_stats is not None else SessionStats()
        self.stats = stats  # expose so DelegateTaskTool can read after run()
        messages = await self._ctx.memory.load(self._ctx.session_id)
        messages = _drop_dangling_tool_calls(messages)
        if user_input is not None:
            messages.append(Message(role="user", content=user_input, created_at=datetime.now(timezone.utc).isoformat()))
            # Persist user message immediately so it survives page refresh
            await self._save_session(
                self._ctx.session_id,
                messages,
                agent_name=self._ctx.agent_name,
                agent_uuid=self._ctx.agent_uuid,
                parent_session_id=self._ctx.parent_session_id,
                status="running",
                max_tokens=self._ctx.max_tokens,
                trigger=self._ctx.trigger,
            )
        elif messages:
            # Resume without new user input.
            # If the last message is from the assistant, inject a continuation
            # prompt so the LLM message alternation (user → assistant) is preserved.
            last = messages[-1]
            if last.role == "assistant":
                messages.append(Message(role="user", content="Continue.", created_at=datetime.now(timezone.utc).isoformat()))
            # If the last message is already from the user, the LLM will
            # simply re-process it — no injection needed.

        turns = 0
        try:
            while True:
                if await self._is_cancelled():
                    await self._save_session(
                        self._ctx.session_id,
                        messages,
                        agent_name=self._ctx.agent_name,
                        agent_uuid=self._ctx.agent_uuid,
                        status="cancelled",
                    )
                    total_ms = (time.monotonic() - session_start) * 1000
                    self._emit("session_end", {
                        "turns": turns,
                        "stopped": True,
                        "total_duration_ms": total_ms,
                    }, duration_ms=total_ms)
                    # Clean up cancel signal file
                    if self._ctx.file_store is not None:
                        try:
                            await self._ctx.file_store.delete(_SI.signal_relpath(self._ctx.session_id, self._ctx.root_session_id))
                        except Exception:
                            pass
                    yield SessionEnd(response=_STOPPED)
                    return

                yield TurnStart(turn=turns)

                llm_start = time.monotonic()
                self._emit("llm_start", {
                    "message_count": len(messages),
                    "messages": [m.to_dict() for m in messages],
                })
                messages_to_send = await self._hook("on_llm_start", list(messages))
                # Strip thinking tokens — stored in history but not sent to LLM
                messages_to_send = [
                    Message(
                        role=m.role,
                        content=m.content,
                        tool_calls=m.tool_calls,
                        tool_call_id=m.tool_call_id,
                        name=m.name,
                        # thinking intentionally omitted
                    )
                    for m in messages_to_send
                ]
                _streamed_text = False
                _streamed_thinking = False
                _stream_fn = getattr(self._llm, "complete_stream", None)
                if _stream_fn is not None:
                    _response_holder = None
                    async for _kind, _payload in _stream_fn(
                        messages=messages_to_send,
                        tools=self._ctx.tool_registry.get_definitions(),
                        system=self._build_system_prompt(),
                    ):
                        if _kind == "text":
                            _streamed_text = True
                            yield TextDelta(content=_payload)
                        elif _kind == "thinking":
                            _streamed_thinking = True
                            yield ThinkingDelta(content=_payload)
                        elif _kind == "done":
                            _response_holder = _payload
                    if _response_holder is None:
                        raise RuntimeError(
                            "complete_stream() terminated without yielding a ('done', LLMResponse) event"
                        )
                    response = _response_holder
                else:
                    response = await self._llm.complete(
                        messages=messages_to_send,
                        tools=self._ctx.tool_registry.get_definitions(),
                        system=self._build_system_prompt(),
                    )
                response = await self._hook("on_llm_end", response)
                llm_ms = (time.monotonic() - llm_start) * 1000
                self._emit("llm_end", {
                    "input_tokens": response.input_tokens,
                    "output_tokens": response.output_tokens,
                    "response": {
                        "content": response.content,
                        "tool_calls": [
                            {"id": tc.id, "name": tc.name, "args": tc.args}
                            for tc in (response.tool_calls or [])
                        ],
                    },
                }, duration_ms=llm_ms)

                input_tokens = response.input_tokens
                output_tokens = response.output_tokens
                _model_id = getattr(self._llm, "model_id", None)
                _model_id_str = _model_id if isinstance(_model_id, str) else ""
                stats.record(TokenUsage(
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                    total_tokens=input_tokens + output_tokens,
                    model_id=_model_id_str,
                ))
                from everstaff.schema.stream import TokenUsageEvent
                yield TokenUsageEvent(
                    model_id=_model_id_str,
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                )

                # Check cancel after LLM completes — covers the window
                # where the user clicked stop while LLM was streaming.
                if await self._is_cancelled():
                    await self._save_session(
                        self._ctx.session_id,
                        messages,
                        agent_name=self._ctx.agent_name,
                        agent_uuid=self._ctx.agent_uuid,
                        status="cancelled",
                    )
                    total_ms = (time.monotonic() - session_start) * 1000
                    self._emit("session_end", {
                        "turns": turns,
                        "stopped": True,
                        "total_duration_ms": total_ms,
                    }, duration_ms=total_ms)
                    if self._ctx.file_store is not None:
                        try:
                            await self._ctx.file_store.delete(_SI.signal_relpath(self._ctx.session_id, self._ctx.root_session_id))
                        except Exception:
                            pass
                    yield SessionEnd(response=_STOPPED)
                    return

                if response.is_final:
                    # Framework fallback: if any child HITL requests remain unresolved, raise
                    if self._pending_child_hitls:
                        raise HumanApprovalRequired(self._pending_child_hitls)
                    if response.thinking and not _streamed_thinking:
                        yield ThinkingDelta(content=response.thinking)
                    if response.content and not _streamed_text:
                        yield TextDelta(content=response.content)
                    messages.append(Message(
                        role="assistant",
                        content=response.content,
                        thinking=response.thinking,
                        created_at=datetime.now(timezone.utc).isoformat(),
                    ))
                    await self._save_session(
                        self._ctx.session_id, messages,
                        agent_name=self._ctx.agent_name,
                        agent_uuid=self._ctx.agent_uuid,
                        parent_session_id=self._ctx.parent_session_id,
                        stats=stats,
                        status="completed",
                        system_prompt=self._build_system_prompt(),
                        max_tokens=self._ctx.max_tokens,
                    )
                    total_ms = (time.monotonic() - session_start) * 1000
                    self._emit("session_end", {
                        "turns": turns,
                        "total_duration_ms": total_ms,
                    }, duration_ms=total_ms)
                    await self._hook_notify("on_session_end", response.content or "")

                    if len(messages) == 2 and self._ctx.parent_session_id is None:
                        await self._generate_title(user_input, response.content or "")

                    # Clean up cancel signal file
                    if self._ctx.file_store is not None:
                        try:
                            await self._ctx.file_store.delete(_SI.signal_relpath(self._ctx.session_id, self._ctx.root_session_id))
                        except Exception:
                            pass
                    yield SessionEnd(response=response.content or "")
                    return

                turns += 1
                # Yield thinking/text content before tool execution so callers
                # (CLI, run()) see the assistant's words even on non-final turns.
                if response.thinking and not _streamed_thinking:
                    yield ThinkingDelta(content=response.thinking)
                if response.content and not _streamed_text:
                    yield TextDelta(content=response.content)
                assistant_msg = Message(
                    role="assistant",
                    content=response.content,
                    tool_calls=[
                        {"id": tc.id, "type": "function",
                         "function": {"name": tc.name, "arguments": json.dumps(tc.args, ensure_ascii=False)}}
                        for tc in response.tool_calls
                    ],
                    thinking=response.thinking,
                    created_at=datetime.now(timezone.utc).isoformat(),
                )
                messages.append(assistant_msg)
                # Incremental save: persist state after each LLM turn
                await self._save_session(
                    self._ctx.session_id,
                    messages,
                    agent_name=self._ctx.agent_name,
                    agent_uuid=self._ctx.agent_uuid,
                    parent_session_id=self._ctx.parent_session_id,
                    stats=stats,
                    status="running",
                    system_prompt=self._build_system_prompt(),
                    max_tokens=self._ctx.max_tokens,
                )

                for tool_call in response.tool_calls:
                    if await self._is_cancelled():
                        await self._save_session(
                            self._ctx.session_id,
                            messages,
                            agent_name=self._ctx.agent_name,
                            agent_uuid=self._ctx.agent_uuid,
                            status="cancelled",
                        )
                        total_ms = (time.monotonic() - session_start) * 1000
                        self._emit("session_end", {
                            "turns": turns,
                            "stopped": True,
                            "total_duration_ms": total_ms,
                        }, duration_ms=total_ms)
                        # Clean up cancel signal file
                        if self._ctx.file_store is not None:
                            try:
                                await self._ctx.file_store.delete(_SI.signal_relpath(self._ctx.session_id, self._ctx.root_session_id))
                            except Exception:
                                pass
                        yield SessionEnd(response=_STOPPED)
                        return

                    # Clear resolved child HITLs when parent properly resumes
                    if tool_call.name == "delegate_task_to_subagent" and tool_call.args.get("resume_session_id"):
                        resume_sid = tool_call.args["resume_session_id"]
                        self._pending_child_hitls = [
                            h for h in self._pending_child_hitls
                            if h.origin_session_id != resume_sid
                        ]

                    tool_args = await self._hook("on_tool_start", tool_call.args, tool_call.name)
                    tcc = ToolCallContext(
                        tool_name=tool_call.name,
                        args=tool_args,
                        agent_context=self._ctx,
                        tool_call_id=tool_call.id,
                    )

                    # Check permission FIRST (may raise HumanApprovalRequired or return denied)
                    try:
                        perm_result = await self._ctx.tool_pipeline.check_permission(tcc)
                    except HumanApprovalRequired as _hitl:
                        for req in _hitl.requests:
                            req.tool_call_id = tool_call.id
                        raise

                    if perm_result is not None:
                        # Permission denied — use denied result, skip tool_start event
                        result = perm_result
                        _ws_before = {}
                        tool_start_t = time.monotonic()
                        self._emit("tool_start", {"tool": tool_call.name, "args": tool_call.args})
                        stats.record_tool_call()
                        yield ToolCallStart(name=tool_call.name, args=tool_call.args)
                    else:
                        # Permission granted — NOW emit tool_start
                        tool_start_t = time.monotonic()
                        self._emit("tool_start", {"tool": tool_call.name, "args": tool_call.args})
                        stats.record_tool_call()
                        yield ToolCallStart(name=tool_call.name, args=tool_call.args)

                        # Snapshot workspace before tool execution
                        _workdir = self._ctx.workdir
                        _ws_before = snapshot_workspace(_workdir) if _workdir else {}

                        # Execute remaining pipeline (PermissionStage already passed)
                        try:
                            result = await self._ctx.tool_pipeline.execute(tcc)
                        except HumanApprovalRequired as _hitl:
                            for req in _hitl.requests:
                                req.tool_call_id = tool_call.id
                            raise
                    result = await self._hook("on_tool_end", result, tool_call.name)
                    tool_ms = (time.monotonic() - tool_start_t) * 1000
                    self._emit("tool_end", {
                        "tool": tool_call.name,
                        "is_error": result.is_error,
                        "result": result.content,
                    }, duration_ms=tool_ms)

                    # Merge child session stats (e.g. from DelegateTaskTool) into parent's children_calls
                    if result.child_stats is not None:
                        stats.merge(result.child_stats)
                    yield ToolCallEnd(name=tool_call.name, result=result.content, is_error=result.is_error)
                    messages.append(Message(role="tool", content=result.content, tool_call_id=tool_call.id, created_at=datetime.now(timezone.utc).isoformat()))
                    # Track child HITL requests from delegate_task_to_subagent results
                    if hasattr(result, '_child_hitl_requests') and result._child_hitl_requests:
                        self._pending_child_hitls.extend(result._child_hitl_requests)

                    # Detect new/modified files and emit FileCreatedEvent
                    if self._ctx.workdir and not result.is_error and _ws_before is not None:
                        _ws_after = snapshot_workspace(self._ctx.workdir)
                        _created, _modified = diff_snapshots(_ws_before, _ws_after)
                        for fp in _created + _modified:
                            try:
                                full = self._ctx.workdir / fp
                                is_dir = full.is_dir()
                                yield FileCreatedEvent(
                                    file_path=fp,
                                    file_name=full.name,
                                    size=0 if is_dir else full.stat().st_size,
                                    mime_type="directory" if is_dir else guess_mime(fp),
                                )
                            except OSError:
                                pass

        except HumanApprovalRequired as hitl_exc:
            # Checkpoint: embed hitl_requests in session.json and save
            from everstaff.schema.hitl_models import HitlRequestRecord, HitlRequestPayload

            new_hitl_data = []
            for req in hitl_exc.requests:
                record = HitlRequestRecord(
                    hitl_id=req.hitl_id,
                    tool_call_id=req.tool_call_id,
                    created_at=_now(),
                    timeout_seconds=req.timeout_seconds,
                    status="pending",
                    origin_session_id=req.origin_session_id or self._ctx.session_id,
                    origin_agent_name=req.origin_agent_name or self._ctx.agent_name,
                    request=HitlRequestPayload(
                        type=req.type,
                        prompt=req.prompt,
                        options=req.options,
                        context=req.context,
                        tool_name=req.tool_name,
                        tool_args=req.tool_args,
                        tool_permission_options=req.tool_permission_options or [],
                    ),
                    response=None,
                )
                new_hitl_data.append(record.model_dump(mode="json"))

            # Merge with existing hitl_requests to preserve resolved entries
            existing_hitls = []
            try:
                import json as _json_mod
                _store = getattr(self._ctx.memory, "_session_store", None) or getattr(self._ctx.memory, "_store", None)
                if _store:
                    _sp = _SI.session_relpath(self._ctx.session_id, self._ctx.root_session_id)
                    raw = await _store.read(_sp)
                    existing_hitls = _json_mod.loads(raw.decode()).get("hitl_requests", [])
            except Exception:
                pass
            new_ids = {h["hitl_id"] for h in new_hitl_data}
            merged_hitls = [h for h in existing_hitls if h.get("hitl_id") not in new_ids] + new_hitl_data

            await self._save_session(
                self._ctx.session_id,
                messages,
                agent_name=self._ctx.agent_name,
                agent_uuid=self._ctx.agent_uuid,
                parent_session_id=self._ctx.parent_session_id,
                stats=stats,
                status="waiting_for_human",
                max_tokens=self._ctx.max_tokens,
                hitl_requests=merged_hitls,
            )
            # Broadcast HITL request to channels — only for daemon-sourced sessions.
            # Web and CLI sessions handle HITL via session.json status polling.
            _is_daemon = (self._ctx.trigger is not None and self._ctx.trigger.source == "daemon")
            if self._ctx.channel_manager is not None and _is_daemon:
                for req in hitl_exc.requests:
                    try:
                        await self._ctx.channel_manager.broadcast(self._ctx.session_id, req)
                    except Exception as bc_err:
                        logger.warning("HITL broadcast failed for %s: %s", req.hitl_id, bc_err)
            for req in hitl_exc.requests:
                self._emit("hitl_requested", {
                    "hitl_id": req.hitl_id,
                    "type": req.type,
                    "prompt": req.prompt,
                })
            total_ms = (time.monotonic() - session_start) * 1000
            self._emit("session_end", {
                "turns": turns,
                "paused_for_hitl": True,
                "total_duration_ms": total_ms,
            }, duration_ms=total_ms)
            # Yield HITL request events so broadcast_fn can notify WS clients
            # (daemon sessions use channel_manager above; web sessions use this path)
            for req in hitl_exc.requests:
                yield HitlRequestEvent(
                    hitl_id=req.hitl_id,
                    session_id=self._ctx.session_id,
                    prompt=req.prompt,
                    hitl_type=req.type,
                    options=req.options or [],
                    context=req.context or "",
                    tool_name=req.tool_name,
                    tool_args=req.tool_args,
                    tool_call_id=req.tool_call_id or "",
                    tool_permission_options=req.tool_permission_options or [],
                )
            # RE-RAISE instead of swallowing: let callers handle HITL
            raise
        except Exception as e:
            stats.record_error()
            try:
                await self._save_session(
                    self._ctx.session_id,
                    messages,
                    agent_name=self._ctx.agent_name,
                    agent_uuid=self._ctx.agent_uuid,
                    status="failed",
                )
            except Exception:
                pass  # don't mask original exception
            self._emit("error", {
                "error_type": type(e).__name__,
                "message": str(e),
                "phase": "runtime_loop",
            })
            yield ErrorEvent(error=str(e))
            raise

    async def run(self, user_input: "str | None") -> str:
        """Thin wrapper around run_stream(). Raises HumanApprovalRequired if HITL triggered."""
        text_so_far = ""
        async for event in self.run_stream(user_input):
            if isinstance(event, TextDelta):
                text_so_far += event.content
            elif isinstance(event, SessionEnd):
                return event.response or ""
        return text_so_far
