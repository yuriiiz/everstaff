# LarkWs Refactor Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Split LarkWsChannel into a shared-connection layer (one WS per app_id) and a thin channel layer (per chat_id), add message reception via EventBus, move token storage to sessions_dir, and annotate card actions with `type` field.

**Architecture:** New `LarkWsConnection` class manages one WebSocket per app_id, handles card action dispatch and message reception. Existing `LarkWsChannel` is slimmed to an outbound-only HitlChannel that delegates to a shared connection. Incoming messages are published to EventBus as `AgentEvent(type="lark_message")` with `target_agent` resolved by chat_id→agent mapping built at daemon startup.

**Tech Stack:** lark-oapi SDK (WebSocket), asyncio, httpx/aiohttp

---

### Task 1: Create LarkWsConnection

**Files:**
- Create: `src/everstaff/channels/lark_ws_connection.py`
- Test: `tests/test_channels/test_lark_ws_connection.py`

This is the core new class. It owns the WebSocket thread, HTTP helpers, and event dispatch.

**Step 1: Write tests**

```python
# tests/test_channels/test_lark_ws_connection.py
"""Tests for LarkWsConnection."""
import pytest
from unittest.mock import AsyncMock, patch, MagicMock

from everstaff.channels.lark_ws_connection import LarkWsConnection


def test_connection_init():
    conn = LarkWsConnection(
        app_id="cli_xxx", app_secret="secret", domain="feishu",
    )
    assert conn._app_id == "cli_xxx"
    assert conn._started is False


def test_register_chat_route():
    conn = LarkWsConnection(
        app_id="cli_xxx", app_secret="secret", domain="feishu",
    )
    conn.register_chat_route("oc_chatA", "agent_a")
    conn.register_chat_route("oc_chatB", "agent_b")
    assert conn._chat_to_agent == {"oc_chatA": "agent_a", "oc_chatB": "agent_b"}


def test_resolve_agent_for_chat():
    conn = LarkWsConnection(
        app_id="cli_xxx", app_secret="secret", domain="feishu",
    )
    conn.register_chat_route("oc_chatA", "agent_a")
    assert conn._resolve_agent("oc_chatA") == "agent_a"
    assert conn._resolve_agent("oc_unknown") is None


def test_parse_card_action_hitl():
    value = {"type": "hitl", "hitl_id": "h1", "decision": "approved", "grant_scope": "session"}
    action_type, parsed = LarkWsConnection._parse_card_value(value)
    assert action_type == "hitl"
    assert parsed["hitl_id"] == "h1"


def test_parse_card_action_unknown_type():
    value = {"type": "feedback", "rating": 5}
    action_type, parsed = LarkWsConnection._parse_card_value(value)
    assert action_type == "feedback"
    assert parsed["rating"] == 5
```

**Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_channels/test_lark_ws_connection.py -v`
Expected: FAIL (module not found)

**Step 3: Implement LarkWsConnection**

```python
# src/everstaff/channels/lark_ws_connection.py
"""LarkWsConnection — one WebSocket per app_id, shared across channels.

Handles:
- WebSocket lifecycle (connect, reconnect via lark-oapi SDK)
- Card action dispatch (by value.type)
- Message reception (p2_im_message_receive_v1)
- HTTP helpers (get_access_token, send_card, update_card)
"""
from __future__ import annotations

import asyncio
import base64
import http
import json
import logging
import threading
import time
from typing import Any, Callable, Awaitable, TYPE_CHECKING

if TYPE_CHECKING:
    from everstaff.channels.manager import ChannelManager
    from everstaff.daemon.event_bus import EventBus

logger = logging.getLogger(__name__)

_DOMAIN_TO_API_BASE = {
    "feishu": "https://open.feishu.cn/open-apis",
    "lark": "https://open.larksuite.com/open-apis",
}


class LarkWsConnection:
    """Manages a single WebSocket connection to Feishu/Lark for one app_id.

    Multiple LarkWsChannel instances can share the same connection.
    Incoming events are dispatched by type:
    - Card actions with type=hitl → channel_manager.resolve()
    - Card actions with other types → EventBus
    - User messages → EventBus as AgentEvent(type="lark_message")
    """

    def __init__(
        self,
        app_id: str,
        app_secret: str,
        domain: str = "feishu",
    ) -> None:
        self._app_id = app_id
        self._app_secret = app_secret
        self._domain = domain
        self._api_base = _DOMAIN_TO_API_BASE.get(domain, _DOMAIN_TO_API_BASE["feishu"])

        # Injected after construction
        self._channel_manager: ChannelManager | None = None
        self._event_bus: EventBus | None = None

        # chat_id → agent_name routing for incoming messages
        self._chat_to_agent: dict[str, str] = {}

        self._started: bool = False
        self._ws_thread: threading.Thread | None = None
        self._app_loop: asyncio.AbstractEventLoop | None = None

    # ── Chat routing ─────────────────────────────────────────────

    def register_chat_route(self, chat_id: str, agent_name: str) -> None:
        """Register a chat_id → agent_name mapping for message routing."""
        self._chat_to_agent[chat_id] = agent_name
        logger.info("registered chat route chat_id=%s agent=%s app=%s", chat_id, agent_name, self._app_id)

    def _resolve_agent(self, chat_id: str) -> str | None:
        """Resolve which agent handles messages from this chat."""
        return self._chat_to_agent.get(chat_id)

    # ── Card value parsing ───────────────────────────────────────

    @staticmethod
    def _parse_card_value(value: dict) -> tuple[str, dict]:
        """Parse a card action value dict. Returns (action_type, value_dict)."""
        action_type = value.get("type", "hitl")
        return action_type, value

    # ── HTTP helpers ─────────────────────────────────────────────

    async def get_access_token(self) -> str:
        import aiohttp
        url = f"{self._api_base}/auth/v3/tenant_access_token/internal"
        async with aiohttp.ClientSession() as s:
            async with s.post(url, json={"app_id": self._app_id, "app_secret": self._app_secret}) as r:
                return (await r.json())["tenant_access_token"]

    async def send_card(self, chat_id: str, card: dict) -> str:
        """Send an interactive card to a specific chat. Returns message_id."""
        import aiohttp
        token = await self.get_access_token()
        url = f"{self._api_base}/im/v1/messages?receive_id_type=chat_id"
        headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
        body = {"receive_id": chat_id, "msg_type": "interactive", "content": json.dumps(card)}
        logger.info("POST url=%s chat_id=%s", url, chat_id)
        async with aiohttp.ClientSession() as s:
            async with s.post(url, headers=headers, json=body) as r:
                data = await r.json()
                mid = data.get("data", {}).get("message_id", "")
                if not mid:
                    logger.error("send_card failed code=%s msg=%s", data.get("code"), data.get("msg"))
                return mid

    async def update_card(self, message_id: str, card: dict) -> None:
        """Update an existing interactive card."""
        import aiohttp
        token = await self.get_access_token()
        url = f"{self._api_base}/im/v1/messages/{message_id}"
        headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
        body = {"msg_type": "interactive", "content": json.dumps(card)}
        async with aiohttp.ClientSession() as s:
            async with s.patch(url, headers=headers, json=body) as r:
                resp_data = await r.json()
                logger.info("update_card status=%s mid=%s", r.status, message_id)

    # ── Card action handler ──────────────────────────────────────

    async def _handle_card_action(self, data: Any) -> dict:
        """Dispatch a card action event by value.type."""
        event = getattr(data, "event", data)
        action = getattr(event, "action", None)
        if action is None:
            logger.warning("card action: no action field")
            return {}

        raw_value = getattr(action, "value", None)
        if isinstance(raw_value, str):
            try:
                value = json.loads(raw_value)
            except (json.JSONDecodeError, TypeError):
                value = {}
        elif isinstance(raw_value, dict):
            value = raw_value
        else:
            value = {}

        # Extract operator
        operator = getattr(event, "operator", None)
        open_id = getattr(operator, "open_id", "lark_user") if operator else "lark_user"
        open_id = open_id or "lark_user"

        action_type, parsed = self._parse_card_value(value)
        logger.info("card action type=%s open_id=%s value=%s", action_type, open_id, parsed)

        if action_type == "hitl":
            return await self._handle_hitl_action(parsed, open_id)
        else:
            # Publish non-HITL card actions to EventBus
            if self._event_bus is not None:
                from everstaff.protocols import AgentEvent
                await self._event_bus.publish(AgentEvent(
                    type="lark_card_action",
                    source=self._app_id,
                    payload={"action_type": action_type, "open_id": open_id, **parsed},
                ))
            return {"toast": {"type": "success", "content": "OK"}}

    async def _handle_hitl_action(self, value: dict, resolved_by: str) -> dict:
        """Handle HITL card action: resolve via channel_manager."""
        hitl_id = value.get("hitl_id", "")
        decision = value.get("decision", "")

        if not hitl_id or not decision:
            logger.warning("hitl action: missing hitl_id=%s or decision=%s", hitl_id, decision)
            return {}

        # Handle form input
        if decision == "__input__":
            raw_form = value.get("form_value")
            if isinstance(raw_form, str):
                try:
                    form_dict = json.loads(raw_form)
                except (json.JSONDecodeError, TypeError):
                    form_dict = {}
            elif isinstance(raw_form, dict):
                form_dict = raw_form
            else:
                form_dict = {}
            decision = form_dict.get("user_input", "")

        grant_scope = value.get("grant_scope")
        permission_pattern = value.get("permission_pattern")

        logger.info("hitl action hitl_id=%s decision=%r by=%s", hitl_id, decision, resolved_by)

        if self._channel_manager is not None and self._app_loop is not None:
            from everstaff.protocols import HitlResolution
            from datetime import datetime, timezone
            resolution = HitlResolution(
                decision=decision,
                resolved_at=datetime.now(timezone.utc),
                resolved_by=resolved_by,
                grant_scope=grant_scope,
                permission_pattern=permission_pattern,
            )
            asyncio.run_coroutine_threadsafe(
                self._channel_manager.resolve(hitl_id, resolution),
                self._app_loop,
            )

        return {"toast": {"type": "success", "content": f"Decision: {decision}"}}

    # ── Message handler ──────────────────────────────────────────

    async def _handle_message(self, data: Any) -> None:
        """Handle an incoming user message: publish to EventBus."""
        event = getattr(data, "event", data)
        message = getattr(event, "message", None)
        sender = getattr(event, "sender", None)
        if message is None:
            logger.warning("message event: no message field")
            return

        chat_id = getattr(message, "chat_id", "")
        message_id = getattr(message, "message_id", "")
        msg_type = getattr(message, "message_type", "text")
        content_raw = getattr(message, "content", "{}")
        sender_id = getattr(getattr(sender, "sender_id", None), "open_id", "") if sender else ""

        # Parse content
        try:
            content = json.loads(content_raw) if isinstance(content_raw, str) else content_raw
        except (json.JSONDecodeError, TypeError):
            content = {"text": str(content_raw)}

        text = content.get("text", "") if isinstance(content, dict) else str(content)

        target_agent = self._resolve_agent(chat_id)
        logger.info("message chat_id=%s sender=%s agent=%s text=%s",
                     chat_id, sender_id, target_agent or "?", text[:80])

        if self._event_bus is not None:
            from everstaff.protocols import AgentEvent
            await self._event_bus.publish(AgentEvent(
                type="lark_message",
                source=self._app_id,
                payload={
                    "chat_id": chat_id,
                    "sender_open_id": sender_id,
                    "content": text,
                    "message_type": msg_type,
                    "message_id": message_id,
                },
                target_agent=target_agent,
            ))

    # ── WS client setup ─────────────────────────────────────────

    def _build_ws_client(self, loop: asyncio.AbstractEventLoop):
        """Build lark-oapi WSClient with card action + message handlers."""
        import lark_oapi as lark
        from lark_oapi.event.callback.model.p2_card_action_trigger import (
            P2CardActionTrigger,
        )
        from lark_oapi.ws.enum import MessageType
        from lark_oapi.ws.const import (
            HEADER_TYPE, HEADER_MESSAGE_ID, HEADER_TRACE_ID,
            HEADER_SUM, HEADER_SEQ, HEADER_BIZ_RT,
        )
        from lark_oapi.ws.model import Response as WsResp
        from lark_oapi.core.const import UTF_8

        def sync_card_handler(data: P2CardActionTrigger):
            """Handle card action in WS thread, dispatch to app loop."""
            if self._app_loop is not None and self._app_loop.is_running():
                future = asyncio.run_coroutine_threadsafe(
                    self._handle_card_action(data), self._app_loop,
                )
                try:
                    return future.result(timeout=5)
                except Exception as exc:
                    logger.error("card action handler error: %s", exc, exc_info=True)
            return {}

        handler_builder = (
            lark.EventDispatcherHandler.builder("", "")
            .register_p2_card_action_trigger(sync_card_handler)
        )

        # Register message handler
        try:
            from lark_oapi.api.im.v1 import P2ImMessageReceiveV1

            def sync_message_handler(data: P2ImMessageReceiveV1):
                if self._app_loop is not None and self._app_loop.is_running():
                    asyncio.run_coroutine_threadsafe(
                        self._handle_message(data), self._app_loop,
                    )

            handler_builder = handler_builder.register_p2_im_message_receive_v1(sync_message_handler)
            logger.info("registered p2_im_message_receive_v1 handler")
        except (ImportError, AttributeError) as exc:
            logger.warning("p2_im_message_receive_v1 not available: %s", exc)

        event_handler = handler_builder.build()

        domain = lark.LARK_DOMAIN if self._domain == "lark" else lark.FEISHU_DOMAIN
        client = lark.ws.Client(
            self._app_id,
            self._app_secret,
            event_handler=event_handler,
            log_level=lark.LogLevel.DEBUG,
            domain=domain,
        )

        # Patch _handle_data_frame: route CARD frames like EVENT
        def _hdr(headers, key: str) -> str:
            for h in headers:
                if h.key == key:
                    return h.value
            return ""

        async def _handle_data_frame(frame) -> None:
            hs = frame.headers
            type_ = _hdr(hs, HEADER_TYPE)
            msg_type = MessageType(type_)

            if msg_type not in (MessageType.EVENT, MessageType.CARD):
                return

            msg_id = _hdr(hs, HEADER_MESSAGE_ID)
            trace_id = _hdr(hs, HEADER_TRACE_ID)
            pl = frame.payload
            sum_ = _hdr(hs, HEADER_SUM)
            seq = _hdr(hs, HEADER_SEQ)
            if sum_ and int(sum_) > 1:
                pl = client._combine(msg_id, int(sum_), int(seq), pl)
                if pl is None:
                    return

            try:
                payload_str = pl.decode(UTF_8)
                logger.info("ws frame type=%s msg_id=%s payload=%s", msg_type.value, msg_id, payload_str[:500])
            except Exception:
                pass

            resp = WsResp(code=http.HTTPStatus.OK)
            try:
                start_ms = int(round(time.time() * 1000))
                result = client._event_handler.do_without_validation(pl)
                elapsed = int(round(time.time() * 1000)) - start_ms
                header = hs.add()
                header.key = HEADER_BIZ_RT
                header.value = str(elapsed)
                if result is not None:
                    marshaled = lark.JSON.marshal(result)
                    resp.data = base64.b64encode(marshaled.encode(UTF_8))
            except Exception as exc:
                from lark_oapi.core.exception import EventException
                if isinstance(exc, EventException) and "processor not found" in str(exc):
                    logger.debug("no handler for type=%s msg_id=%s", msg_type.value, msg_id)
                else:
                    logger.error("handler error type=%s err=%s", msg_type.value, exc, exc_info=True)
                    resp = WsResp(code=http.HTTPStatus.INTERNAL_SERVER_ERROR)

            frame.payload = lark.JSON.marshal(resp).encode(UTF_8)
            await client._write_message(frame.SerializeToString())

        client._handle_data_frame = _handle_data_frame
        return client

    # ── Lifecycle ────────────────────────────────────────────────

    async def start(self) -> None:
        if self._started:
            return
        self._started = True
        loop = asyncio.get_running_loop()
        self._app_loop = loop

        def _run_ws():
            import lark_oapi.ws.client as _ws_mod
            ws_loop = asyncio.new_event_loop()
            asyncio.set_event_loop(ws_loop)
            _ws_mod.loop = ws_loop
            try:
                client = self._build_ws_client(loop)
                logger.info("WS connection started app=%s", self._app_id)
                client.start()
            except Exception as exc:
                logger.error("WS thread failed app=%s err=%s", self._app_id, exc, exc_info=True)

        self._ws_thread = threading.Thread(target=_run_ws, daemon=True)
        self._ws_thread.start()
        logger.info("started WS connection app=%s", self._app_id)

    async def stop(self) -> None:
        self._started = False
        logger.info("stopped WS connection app=%s", self._app_id)
```

**Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_channels/test_lark_ws_connection.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add -f src/everstaff/channels/lark_ws_connection.py tests/test_channels/test_lark_ws_connection.py
git commit -m "feat: add LarkWsConnection — shared WS per app_id"
```

---

### Task 2: Refactor LarkWsChannel to use LarkWsConnection

**Files:**
- Modify: `src/everstaff/channels/lark_ws.py`
- Test: `tests/test_channels/test_lark_ws_channel.py`

Slim down LarkWsChannel to an outbound-only HitlChannel that delegates to a shared connection. Remove all WebSocket, HTTP, and card action handling code.

**Step 1: Write tests**

```python
# tests/test_channels/test_lark_ws_channel.py
"""Tests for refactored LarkWsChannel."""
import pytest
from unittest.mock import AsyncMock, MagicMock

from everstaff.channels.lark_ws import LarkWsChannel
from everstaff.channels.lark_ws_connection import LarkWsConnection


def test_channel_init():
    conn = MagicMock(spec=LarkWsConnection)
    ch = LarkWsChannel(connection=conn, chat_id="oc_chatA", bot_name="Bot")
    assert ch._chat_id == "oc_chatA"
    assert ch._bot_name == "Bot"
    assert ch._connection is conn


def test_build_card_has_type_hitl():
    """All HITL card button values must include type=hitl."""
    conn = MagicMock(spec=LarkWsConnection)
    ch = LarkWsChannel(connection=conn, chat_id="oc_chatA")

    from everstaff.protocols import HitlRequest
    request = HitlRequest(hitl_id="h1", type="approve_reject", prompt="Approve?")
    card = ch._build_card(request, "h1")

    # Find action buttons
    actions = [e for e in card["elements"] if e.get("tag") == "action"]
    assert len(actions) == 1
    for btn in actions[0]["actions"]:
        value = btn["value"]
        assert value["type"] == "hitl", f"Button missing type=hitl: {value}"


@pytest.mark.asyncio
async def test_send_request_delegates_to_connection():
    conn = MagicMock(spec=LarkWsConnection)
    conn.send_card = AsyncMock(return_value="msg_001")
    ch = LarkWsChannel(connection=conn, chat_id="oc_chatA", bot_name="Bot")

    from everstaff.protocols import HitlRequest
    request = HitlRequest(hitl_id="h1", type="approve_reject", prompt="Approve?")
    await ch.send_request("session1", request)

    conn.send_card.assert_called_once()
    call_args = conn.send_card.call_args
    assert call_args[0][0] == "oc_chatA"  # chat_id
```

**Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_channels/test_lark_ws_channel.py -v`
Expected: FAIL (LarkWsChannel constructor changed)

**Step 3: Rewrite LarkWsChannel**

Rewrite `src/everstaff/channels/lark_ws.py`. Remove:
- `_get_access_token`, `_send_card`, `_update_card` (moved to Connection)
- `_parse_card_action`, `_handle_card_action` (moved to Connection)
- `_build_ws_client`, `start`, `stop` WS logic (moved to Connection)

Keep:
- `_build_card`, `_build_resolved_card`, `_build_notify_card` (card builders)
- `send_request`, `on_resolved` (HitlChannel protocol)

New constructor:

```python
class LarkWsChannel:
    def __init__(
        self,
        connection: LarkWsConnection,
        chat_id: str = "",
        bot_name: str = "Agent",
        file_store=None,
    ) -> None:
        self._connection = connection
        self._chat_id = chat_id
        self._bot_name = bot_name
        self._file_store = file_store
        self._app_id = connection._app_id  # for compat
        self._hitl_message_ids: dict[str, str] = {}
        self._hitl_requests: dict[str, HitlRequest] = {}
```

All `_build_card` button values must include `"type": "hitl"` in every value dict. For example:

```python
# Before:
{"hitl_id": hitl_id, "decision": "approved"}
# After:
{"type": "hitl", "hitl_id": hitl_id, "decision": "approved"}
```

`send_request` calls `self._connection.send_card(self._chat_id, card)`.
`on_resolved` calls `self._connection.update_card(message_id, card)`.
`start()` and `stop()` are no-ops (connection lifecycle is managed externally).

**Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_channels/test_lark_ws_channel.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add src/everstaff/channels/lark_ws.py tests/test_channels/test_lark_ws_channel.py
git commit -m "refactor: slim LarkWsChannel to outbound-only, delegate to LarkWsConnection"
```

---

### Task 3: Update factories and startup to build connection registry

**Files:**
- Modify: `src/everstaff/core/factories.py`
- Modify: `src/everstaff/api/__init__.py`
- Test: `tests/test_channels/test_lark_ws_factory.py`

**Step 1: Write tests**

```python
# tests/test_channels/test_lark_ws_factory.py
"""Tests for LarkWs connection registry construction."""
from everstaff.core.config import LarkWsChannelConfig


def test_build_lark_connections_deduplicates():
    """Two configs with same app_id should produce one connection."""
    from everstaff.core.factories import build_lark_connections

    configs = {
        "ch_a": LarkWsChannelConfig(type="lark_ws", app_id="cli_xxx", app_secret="s", chat_id="oc_a"),
        "ch_b": LarkWsChannelConfig(type="lark_ws", app_id="cli_xxx", app_secret="s", chat_id="oc_b"),
    }
    connections = build_lark_connections(configs)
    assert len(connections) == 1
    assert "cli_xxx" in connections


def test_build_lark_connections_multiple_apps():
    """Different app_ids get separate connections."""
    from everstaff.core.factories import build_lark_connections

    configs = {
        "ch_a": LarkWsChannelConfig(type="lark_ws", app_id="app1", app_secret="s1", chat_id="oc_a"),
        "ch_b": LarkWsChannelConfig(type="lark_ws", app_id="app2", app_secret="s2", chat_id="oc_b"),
    }
    connections = build_lark_connections(configs)
    assert len(connections) == 2
    assert "app1" in connections
    assert "app2" in connections
```

**Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_channels/test_lark_ws_factory.py -v`
Expected: FAIL

**Step 3: Implement**

Add to `src/everstaff/core/factories.py`:

```python
def build_lark_connections(channel_configs: dict) -> dict:
    """Build a {app_id: LarkWsConnection} registry, deduplicating by app_id."""
    from everstaff.core.config import LarkWsChannelConfig
    from everstaff.channels.lark_ws_connection import LarkWsConnection

    connections: dict[str, LarkWsConnection] = {}
    for name, cfg in channel_configs.items():
        if not isinstance(cfg, LarkWsChannelConfig):
            continue
        if cfg.app_id not in connections:
            connections[cfg.app_id] = LarkWsConnection(
                app_id=cfg.app_id,
                app_secret=cfg.app_secret,
                domain=cfg.domain,
            )
    return connections
```

Update `build_channel()` to accept an optional `lark_connections` dict. When building a `LarkWsChannelConfig`, look up the shared connection:

```python
def build_channel(cfg, file_store, lark_connections=None):
    # ...
    elif isinstance(cfg, LarkWsChannelConfig):
        conn = None
        if lark_connections:
            conn = lark_connections.get(cfg.app_id)
        if conn is None:
            # Fallback: create standalone connection (backward compat during transition)
            from everstaff.channels.lark_ws_connection import LarkWsConnection
            conn = LarkWsConnection(app_id=cfg.app_id, app_secret=cfg.app_secret, domain=cfg.domain)
        from everstaff.channels.lark_ws import LarkWsChannel
        return LarkWsChannel(connection=conn, chat_id=cfg.chat_id, bot_name=cfg.bot_name, file_store=file_store)
```

Update `build_channel_registry()` and `build_channel_manager_from_registry()` to pass `lark_connections` through.

In `src/everstaff/api/__init__.py`, build connections before channels:

```python
from everstaff.core.factories import build_lark_connections

lark_connections = build_lark_connections(config.channels or {})
channel_registry = build_channel_registry(config, _file_store, lark_connections=lark_connections)
channel_manager = build_channel_manager_from_registry(channel_registry, config)

# Inject channel_manager and event_bus into connections
# (event_bus comes from daemon, set later if daemon is enabled)
for conn in lark_connections.values():
    conn._channel_manager = channel_manager

# Start/stop connections alongside channels in lifespan
app.state.lark_connections = lark_connections
```

In lifespan startup, after `cm.start_all()`:
```python
for conn in app.state.lark_connections.values():
    await conn.start()
```

In lifespan shutdown, before `cm.stop_all()`:
```python
for conn in app.state.lark_connections.values():
    await conn.stop()
```

**Step 4: Run tests**

Run: `uv run pytest tests/test_channels/test_lark_ws_factory.py tests/test_channels/test_lark_ws_channel.py tests/test_channels/test_lark_ws_connection.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add src/everstaff/core/factories.py src/everstaff/api/__init__.py tests/test_channels/test_lark_ws_factory.py
git commit -m "feat: build connection registry, wire into startup"
```

---

### Task 4: Wire EventBus into connections for message routing

**Files:**
- Modify: `src/everstaff/api/__init__.py`
- Modify: `src/everstaff/daemon/agent_daemon.py`
- Modify: `src/everstaff/daemon/agent_loop.py`

This task connects the daemon's EventBus to LarkWsConnections and sets up chat_id→agent routing.

**Step 1: Modify AgentDaemon to inject EventBus into connections**

In `agent_daemon.py`, add `lark_connections` parameter:

```python
def __init__(self, ..., lark_connections: dict | None = None):
    # ...
    self._lark_connections = lark_connections or {}
```

In `start()`, after creating `_event_bus`, inject it into connections:

```python
for conn in self._lark_connections.values():
    conn._event_bus = self._event_bus
```

In `_start_agent()`, register chat routes from agent's hitl_channels:

```python
# Register chat_id → agent routes on LarkWsConnections
for ref in spec.hitl_channels:
    channel = self._channel_registry.get(ref.ref)
    if channel is None:
        continue
    overrides = ref.overrides()
    chat_id = overrides.get("chat_id") or getattr(channel, "_chat_id", "")
    if chat_id:
        # Find which connection this channel uses
        app_id = getattr(channel, "_app_id", "")
        conn = self._lark_connections.get(app_id)
        if conn:
            conn.register_chat_route(chat_id, name)
```

**Step 2: Pass lark_connections from api/__init__.py to AgentDaemon**

```python
daemon = AgentDaemon(
    # ... existing args ...
    lark_connections=lark_connections,
)
```

**Step 3: Update AgentLoop to pass sender_open_id to runtime**

In `agent_loop.py`, modify the act phase. When event type is `lark_message`, extract `sender_open_id` and pass it via trigger:

The existing code already passes `trigger=event` to `runtime_factory()`:
```python
runtime = self._runtime_factory(
    session_id=loop_session_id,
    trigger=event,  # ← event.payload.sender_open_id is already here
    channel_manager=scoped_cm,
)
```

The `AgentBuilder._register_feishu_tools` already reads `self._trigger.payload.get("sender_open_id", "")`. So no change needed in AgentLoop itself — the trigger payload flows through naturally.

**Step 4: Run all tests**

Run: `uv run pytest tests/test_feishu/ tests/test_channels/ -v`
Expected: PASS

**Step 5: Commit**

```bash
git add src/everstaff/api/__init__.py src/everstaff/daemon/agent_daemon.py
git commit -m "feat: wire EventBus into LarkWsConnections for message routing"
```

---

### Task 5: Move token storage to sessions_dir

**Files:**
- Modify: `src/everstaff/feishu/token_store.py`
- Modify: `src/everstaff/feishu/tools/registry.py`
- Modify: `src/everstaff/feishu/tools/doc_tools.py`
- Modify: `src/everstaff/feishu/tools/calendar_tools.py`
- Modify: `src/everstaff/feishu/tools/task_tools.py`
- Modify: `src/everstaff/feishu/tools/im_tools.py`
- Modify: `src/everstaff/feishu/auto_auth.py`
- Modify: `src/everstaff/builder/agent_builder.py`
- Test: `tests/test_feishu/test_token_store.py` (update existing)

**Step 1: Update FileTokenStore — remove default, require base_dir**

In `src/everstaff/feishu/token_store.py`:

```python
class FileTokenStore:
    def __init__(self, base_dir: Path) -> None:
        self._dir = Path(base_dir)
```

Remove the `if base_dir is None: base_dir = Path.home() / ...` default.

**Step 2: Update tool factories to accept token_store**

In each `make_feishu_*_tools()` function, replace:
```python
store = FileTokenStore()
```
with:
```python
# token_store is now a required parameter
```

Add `token_store` parameter to each factory function signature. Pass it through from `create_feishu_tools()`.

In `src/everstaff/feishu/tools/registry.py`:

```python
def create_feishu_tools(
    *,
    app_id: str,
    app_secret: str,
    domain: str = "feishu",
    categories: list[str] | None = None,
    auth_handler: Any = None,
    user_open_id: str = "",
    token_store: Any = None,
) -> list[Any]:
```

Pass `token_store=token_store` to each `make_feishu_*_tools()` call.

**Step 3: Update AgentBuilder to create token_store with sessions_dir**

In `src/everstaff/builder/agent_builder.py`, `_register_feishu_tools`:

```python
from everstaff.feishu.token_store import FileTokenStore
token_store = FileTokenStore(
    base_dir=Path(self._env.config.sessions_dir).expanduser() / "feishu-tokens"
)

tools = create_feishu_tools(
    # ... existing args ...
    token_store=token_store,
)
```

**Step 4: Update tests**

Update `tests/test_feishu/test_token_store.py` — all existing tests already use `tmp_path`, just verify that `FileTokenStore()` without args raises TypeError.

**Step 5: Run tests**

Run: `uv run pytest tests/test_feishu/ -v`
Expected: PASS

**Step 6: Commit**

```bash
git add src/everstaff/feishu/token_store.py src/everstaff/feishu/tools/ src/everstaff/feishu/auto_auth.py src/everstaff/builder/agent_builder.py tests/test_feishu/
git commit -m "refactor: move token storage to sessions_dir/feishu-tokens"
```

---

### Task 6: Add type=hitl to all card button values

**Files:**
- Modify: `src/everstaff/channels/lark_ws.py`
- Test: update `tests/test_channels/test_lark_ws_channel.py`

This may already be done in Task 2 if the channel rewrite includes it. If not:

**Step 1: Update _build_card**

Every button value dict in `_build_card` must include `"type": "hitl"`. Search for all `"value":` dicts in the method and add `"type": "hitl"` to each.

Patterns to update:
- `{"hitl_id": hitl_id, "decision": "approved"}` → `{"type": "hitl", "hitl_id": hitl_id, "decision": "approved"}`
- `{"hitl_id": hitl_id, "decision": opt["id"]}` → `{"type": "hitl", "hitl_id": hitl_id, "decision": opt["id"]}`
- All permission option buttons
- Form submit buttons

**Step 2: Run tests**

Run: `uv run pytest tests/test_channels/test_lark_ws_channel.py -v`
Expected: PASS (test from Task 2 already checks for type=hitl)

**Step 3: Commit**

```bash
git add src/everstaff/channels/lark_ws.py
git commit -m "feat: add type=hitl to all card button values"
```

---

### Task 7: Update FeishuAuthHandler for new connection model

**Files:**
- Modify: `src/everstaff/feishu/auth_handler.py`
- Test: verify existing tests pass

The `FeishuAuthHandler` currently wraps a `LarkWsChannel` instance and calls `_send_card`, `_update_card` directly. Update it to work with the new architecture where cards are sent via `connection.send_card(chat_id, card)`.

**Step 1: Update FeishuAuthHandler**

```python
# src/everstaff/feishu/auth_handler.py
class FeishuAuthHandler:
    def __init__(self, channel):
        self._channel = channel

    async def send_card(self, card: dict) -> str:
        return await self._channel._connection.send_card(self._channel._chat_id, card)

    async def update_card(self, message_id: str, card: dict) -> None:
        await self._channel._connection.update_card(message_id, card)
```

**Step 2: Run all tests**

Run: `uv run pytest tests/test_feishu/ tests/test_channels/ -v`
Expected: PASS

**Step 3: Commit**

```bash
git add src/everstaff/feishu/auth_handler.py
git commit -m "refactor: update FeishuAuthHandler for connection model"
```

---

### Task 8: Full integration test

**Files:**
- Test: `tests/test_channels/test_lark_ws_integration.py`

**Step 1: Write integration test**

```python
# tests/test_channels/test_lark_ws_integration.py
"""Integration test: multiple channels sharing one connection."""
from unittest.mock import MagicMock

from everstaff.channels.lark_ws_connection import LarkWsConnection
from everstaff.channels.lark_ws import LarkWsChannel
from everstaff.core.config import LarkWsChannelConfig
from everstaff.core.factories import build_lark_connections


def test_two_channels_share_connection():
    configs = {
        "ch_a": LarkWsChannelConfig(type="lark_ws", app_id="app1", app_secret="s", chat_id="oc_a"),
        "ch_b": LarkWsChannelConfig(type="lark_ws", app_id="app1", app_secret="s", chat_id="oc_b"),
    }
    connections = build_lark_connections(configs)
    assert len(connections) == 1

    conn = connections["app1"]
    ch_a = LarkWsChannel(connection=conn, chat_id="oc_a")
    ch_b = LarkWsChannel(connection=conn, chat_id="oc_b")
    assert ch_a._connection is ch_b._connection


def test_chat_routing():
    conn = LarkWsConnection(app_id="app1", app_secret="s")
    conn.register_chat_route("oc_a", "agent_a")
    conn.register_chat_route("oc_b", "agent_b")
    assert conn._resolve_agent("oc_a") == "agent_a"
    assert conn._resolve_agent("oc_b") == "agent_b"
    assert conn._resolve_agent("oc_unknown") is None
```

**Step 2: Run all tests**

Run: `uv run pytest tests/test_feishu/ tests/test_channels/ -v`
Expected: ALL PASS

**Step 3: Commit**

```bash
git add -f tests/test_channels/test_lark_ws_integration.py
git commit -m "test: add integration test for shared LarkWs connection"
```
