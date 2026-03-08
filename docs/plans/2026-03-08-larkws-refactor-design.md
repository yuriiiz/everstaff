# LarkWs Refactor — Design

## Goal

Refactor LarkWsChannel into a two-layer architecture: one WebSocket connection per app_id shared across agents, with chat_id-based message routing and general-purpose interaction support beyond HITL.

## Changes

### 1. Architecture Split

**LarkWsConnection** (`channels/lark_ws_connection.py`) — one instance per app_id:
- Manages one WebSocket long connection via `lark.ws.Client`
- Registers `p2_card_action_trigger` + `p2_im_message_receive_v1`
- Dispatches card actions by `value.type` (`"hitl"` → channel_manager, others → EventBus)
- Dispatches incoming messages as `AgentEvent(type="lark_message")` to EventBus
- Owns HTTP helpers: `get_access_token()`, `send_card()`, `update_card()`
- Lifecycle: `start()` / `stop()`

**LarkWsChannel** (`channels/lark_ws.py`) — one instance per config entry:
- Thin outbound wrapper holding `chat_id`, `bot_name`, `file_store`
- References a shared `LarkWsConnection`
- Implements `HitlChannel` protocol (`send_request` / `on_resolved`)
- Delegates HTTP calls to connection: `connection.send_card(chat_id, card)`
- No WebSocket thread, no event handling

### 2. Connection Registry

Built at startup in `api/__init__.py` and `core/factories.py`:

```python
# Deduplicate by app_id — one connection per app
lark_connections: dict[str, LarkWsConnection] = {}
for name, ch_cfg in config.channels.items():
    if isinstance(ch_cfg, LarkWsChannelConfig):
        if ch_cfg.app_id not in lark_connections:
            lark_connections[ch_cfg.app_id] = LarkWsConnection(
                app_id=ch_cfg.app_id,
                app_secret=ch_cfg.app_secret,
                domain=ch_cfg.domain,
            )
```

Connections are started/stopped alongside channels in lifespan.

### 3. Event Flow

**Card action callback:**
1. Connection parses `value.type` from button value dict
2. `type == "hitl"` → calls `channel_manager.resolve(hitl_id, resolution)`
3. Other types → publishes `AgentEvent(type="lark_card_action", payload={...})` to EventBus

**User message (`p2_im_message_receive_v1`):**
1. Connection extracts `chat_id`, `sender.open_id`, `message.content`, `message_id`
2. Publishes to EventBus:
   ```python
   AgentEvent(
       type="lark_message",
       source=app_id,
       payload={
           "chat_id": "oc_xxx",
           "sender_open_id": "ou_xxx",
           "content": "帮我查看今天的日程",
           "message_id": "om_xxx",
       },
   )
   ```

### 4. Daemon Routing

AgentLoop builds a routing filter from agent spec's `hitl_channels`:

```yaml
hitl_channels:
  - ref: lark-main
    chat_id: oc_chatA
```

→ Subscribe to EventBus with filter: only accept `lark_message` events where `payload.chat_id == oc_chatA`.

Multiple agents can reference the same channel name with different `chat_id` overrides; each gets only its own messages.

### 5. Card Value Format

All card buttons include `"type"` field. No backward compatibility needed.

HITL buttons:
```json
{"type": "hitl", "hitl_id": "xxx", "decision": "approved", "grant_scope": "session"}
```

### 6. Token Storage

`FileTokenStore.base_dir` changes from `~/.everstaff/feishu-tokens/` to `{sessions_dir}/feishu-tokens/`.

- `FileTokenStore.__init__` requires explicit `base_dir` parameter (no default)
- `AgentBuilder._register_feishu_tools` passes `Path(sessions_dir) / "feishu-tokens"` when creating tool factories
- All tool factory functions (`make_feishu_doc_tools`, etc.) accept `token_store` parameter instead of creating their own

### 7. File Changes

| File | Change |
|------|--------|
| New `channels/lark_ws_connection.py` | WS connection management, event dispatch |
| Refactor `channels/lark_ws.py` | Slim down to outbound HitlChannel wrapper |
| Modify `core/factories.py` | Build connection registry, pass connections to channels |
| Modify `api/__init__.py` | Startup: create shared connections, start/stop them |
| Modify `daemon/agent_loop.py` | Add `lark_message` event filter based on chat_id |
| Modify `feishu/token_store.py` | Remove default base_dir, require explicit parameter |
| Modify `feishu/tools/*.py` | Accept `token_store` parameter |
| Modify `feishu/tools/registry.py` | Pass `token_store` through |
| Modify `builder/agent_builder.py` | Pass sessions_dir-based token_store to tool factories |
| Modify `lark_ws.py _build_card` | Add `"type": "hitl"` to all button values |
