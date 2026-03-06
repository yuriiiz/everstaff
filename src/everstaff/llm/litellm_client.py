from __future__ import annotations

import ast
import json
import logging
import re
from typing import Any
from uuid import uuid4

import litellm
from litellm.llms.openai.chat.gpt_transformation import OpenAIChatCompletionStreamingHandler

from everstaff.protocols import LLMResponse, Message, ToolCallRequest, ToolDefinition

logger = logging.getLogger(__name__)

# litellm._turn_on_debug()

# ---------------------------------------------------------------------------
# Monkey-patch: LiteLLM's chunk_parser does chunk["id"] (hard key access)
# which crashes on providers like MiniMax that omit "id" in some streaming
# chunks (e.g. usage-only or heartbeat chunks).  Use .get() instead.
# ---------------------------------------------------------------------------
_original_chunk_parser = OpenAIChatCompletionStreamingHandler.chunk_parser


def _safe_chunk_parser(self, chunk: dict):
    if "id" not in chunk:
        chunk["id"] = ""
    return _original_chunk_parser(self, chunk)


OpenAIChatCompletionStreamingHandler.chunk_parser = _safe_chunk_parser

# ---------------------------------------------------------------------------
# Fallback: extract tool calls from XML embedded in content text.
# Some models (e.g. MiniMax) occasionally emit tool calls as XML in the
# content field instead of using the API's tool_calls mechanism.
# Supported formats:
#   <tool_call>  /  <minimax:tool_call>  /  <invoke name="...">
# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------
# Streaming parser for <think>...</think> blocks embedded in content text.
# Some models (e.g. MiniMax) emit reasoning inside <think> XML tags in the
# content field instead of using a dedicated thinking/reasoning_content field.
# ---------------------------------------------------------------------------

class _ThinkTagStreamParser:
    """Separates <think>...</think> thinking content from regular text in streaming chunks.

    Usage::
        parser = _ThinkTagStreamParser()
        for kind, text in parser.feed(chunk):
            ...  # kind is "text" or "thinking"
        for kind, text in parser.flush():
            ...  # flush any buffered partial-tag bytes at end of stream
    """

    _OPEN = "<think>"
    _CLOSE = "</think>"

    def __init__(self) -> None:
        self._in_think = False
        self._pending = ""  # buffered chars that might be part of an opening/closing tag

    def feed(self, chunk: str) -> list[tuple[str, str]]:
        events: list[tuple[str, str]] = []
        buf = self._pending + chunk
        self._pending = ""

        while buf:
            tag = self._CLOSE if self._in_think else self._OPEN
            idx = buf.find(tag)
            if idx == -1:
                # Tag not found; check if end of buf could be start of the tag
                for partial_len in range(min(len(tag) - 1, len(buf)), 0, -1):
                    if buf.endswith(tag[:partial_len]):
                        flush = buf[:-partial_len]
                        if flush:
                            events.append(("thinking" if self._in_think else "text", flush))
                        self._pending = buf[-partial_len:]
                        return events
                # No partial tag at end — emit everything
                if buf:
                    events.append(("thinking" if self._in_think else "text", buf))
                buf = ""
            else:
                # Tag found
                if idx > 0:
                    events.append(("thinking" if self._in_think else "text", buf[:idx]))
                buf = buf[idx + len(tag):]
                self._in_think = not self._in_think

        return events

    def flush(self) -> list[tuple[str, str]]:
        """Emit any buffered partial-tag content at end of stream."""
        if not self._pending:
            return []
        kind = "thinking" if self._in_think else "text"
        result = [(kind, self._pending)]
        self._pending = ""
        return result


def _extract_think_tags(content: str) -> tuple[str | None, str]:
    """Extract <think>...</think> blocks from a completed content string.

    Returns (thinking_text_or_None, cleaned_content).
    """
    parts: list[str] = []

    def _collect(m: re.Match) -> str:
        parts.append(m.group(1))
        return ""

    cleaned = re.sub(r"<think>(.*?)</think>", _collect, content, flags=re.DOTALL)
    return ("".join(parts) or None), cleaned.lstrip("\n")


_XML_TOOL_CALL_RE = re.compile(
    r"<(?:[\w-]+:)?tool_call>\s*"          # opening <tool_call> or <prefix:tool_call>
    r"<invoke\s+name=\"([^\"]+)\">\s*"     # <invoke name="tool_name">
    r"(.*?)"                               # parameters block
    r"</invoke>\s*"
    r"</(?:[\w-]+:)?tool_call>",
    re.DOTALL,
)
_XML_PARAM_RE = re.compile(
    r"<parameter\s+name=\"([^\"]+)\">(.*?)</parameter>",
    re.DOTALL,
)


def _parse_xml_tool_calls(content: str) -> tuple[list[ToolCallRequest], str]:
    """Extract XML-style tool calls from content.

    Returns (tool_calls, cleaned_content) where cleaned_content has the XML
    blocks removed.
    """
    tool_calls: list[ToolCallRequest] = []
    for m in _XML_TOOL_CALL_RE.finditer(content):
        name = m.group(1)
        params_block = m.group(2)
        args: dict[str, Any] = {}
        for pm in _XML_PARAM_RE.finditer(params_block):
            key = pm.group(1)
            val = pm.group(2).strip()
            # Try to parse as JSON for non-string values
            try:
                args[key] = json.loads(val)
            except (json.JSONDecodeError, ValueError):
                args[key] = val
        tool_calls.append(ToolCallRequest(
            id=f"xmlfallback_{uuid4().hex[:12]}",
            name=name,
            args=args,
        ))
    if tool_calls:
        cleaned = _XML_TOOL_CALL_RE.sub("", content).strip()
        return tool_calls, cleaned
    return [], content


def _params_to_json_schema(t: Any) -> dict[str, Any]:
    """Convert a ToolDefinition's parameters to a JSON Schema dict.

    Handles two ToolDefinition shapes:
    - protocols.ToolDefinition: parameters is already a dict (JSON Schema)
    - schema.tool_spec.ToolDefinition: parameters is list[ToolParameter]
    """
    params = t.parameters
    if isinstance(params, dict):
        return params
    # list[ToolParameter] — convert to JSON Schema object
    if hasattr(t, "json_schema") and t.json_schema:
        return t.json_schema
    properties: dict[str, Any] = {}
    required: list[str] = []
    for p in params:
        prop: dict[str, Any] = {"type": p.type}
        if p.description:
            prop["description"] = p.description
        if not p.required and p.default is not None:
            prop["default"] = p.default
        properties[p.name] = prop
        if p.required:
            required.append(p.name)
    schema: dict[str, Any] = {"type": "object", "properties": properties}
    if required:
        schema["required"] = required
    return schema


class LiteLLMClient:
    def __init__(self, model: str, **kwargs: Any) -> None:
        self._model = model
        self._kwargs = kwargs

    @property
    def model_id(self) -> str:
        """Return the model identifier for stats recording."""
        return self._model

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

        response = await litellm.acompletion(
            model=self._model,
            messages=msgs,
            tools=litellm_tools,
            **self._kwargs,
        )

        msg = response.choices[0].message
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

        # Fallback: extract XML-style tool calls from content when the model
        # embeds them in the text instead of using the function calling API.
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

        # Extract thinking/reasoning tokens
        thinking: str | None = getattr(msg, "thinking", None)
        if not thinking:
            thinking = getattr(msg, "reasoning_content", None) or None
        # Fallback: extract <think>...</think> tags from content for models that
        # embed thinking inline (e.g. MiniMax) when no dedicated thinking field exists.
        if not thinking and content:
            extracted_thinking, content = _extract_think_tags(content)
            if extracted_thinking:
                thinking = extracted_thinking
                content = content or None

        # Extract token usage from response.usage (provider may omit it)
        usage = getattr(response, "usage", None)
        input_tokens = int(getattr(usage, "prompt_tokens", 0) or 0)
        output_tokens = int(getattr(usage, "completion_tokens", 0) or 0)

        return LLMResponse(
            content=content,
            tool_calls=tool_calls,
            thinking=thinking,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
        )

    async def complete_stream(
        self,
        messages: list[Message],
        tools: list[ToolDefinition],
        system: str | None = None,
    ):
        """Stream LLM response as an async generator.

        Yields:
            ("text", str)          — each text token as it arrives
            ("done", LLMResponse)  — final item with full response (tool calls, thinking, usage)
        """
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

        full_content: list[str] = []
        thinking_chunks: list[str] = []
        tool_calls_acc: dict[int, dict] = {}  # index → {id, name, args_str}
        input_tokens = 0
        output_tokens = 0

        parser = _ThinkTagStreamParser()

        stream = await litellm.acompletion(
            model=self._model,
            messages=msgs,
            tools=litellm_tools,
            stream=True,
            stream_options={"include_usage": True},
            **self._kwargs,
        )

        async for chunk in stream:
            delta = chunk.choices[0].delta

            # Text content — route through <think> tag parser
            if delta.content:
                for kind, text in parser.feed(delta.content):
                    if kind == "thinking":
                        thinking_chunks.append(text)
                        yield ("thinking", text)
                    else:
                        full_content.append(text)
                        yield ("text", text)

            # Thinking tokens from dedicated thinking field (e.g. Claude Extended Thinking)
            thinking_chunk = getattr(delta, "thinking", None) or getattr(delta, "reasoning_content", None)
            if thinking_chunk:
                thinking_chunks.append(thinking_chunk)
                yield ("thinking", thinking_chunk)

            # Tool calls — accumulate partial chunks by index
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

            # Usage (last chunk for most providers)
            usage = getattr(chunk, "usage", None)
            if usage:
                input_tokens = int(getattr(usage, "prompt_tokens", 0) or 0)
                output_tokens = int(getattr(usage, "completion_tokens", 0) or 0)

        # Flush any remaining partial-tag content from the parser
        for kind, text in parser.flush():
            if kind == "thinking":
                thinking_chunks.append(text)
                yield ("thinking", text)
            else:
                full_content.append(text)
                yield ("text", text)

        # Build final tool call list
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

        # XML fallback for models that embed tool calls in text
        if not tool_calls and content and litellm_tools:
            xml_calls, cleaned_content = _parse_xml_tool_calls(content)
            if xml_calls:
                logger.warning(
                    "Model %s returned %d tool call(s) as XML in content (streaming); using fallback parser",
                    self._model, len(xml_calls),
                )
                tool_calls = xml_calls
                content = cleaned_content or None

        yield ("done", LLMResponse(
            content=content,
            tool_calls=tool_calls,
            thinking=thinking,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
        ))
