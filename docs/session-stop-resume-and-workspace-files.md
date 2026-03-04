# Session Stop/Resume & Workspace Files — Frontend Integration Guide

## 1. Session Stop/Resume

### Problem

Agent sessions can get stuck in tool-call loops. Users need to stop a session and continue the conversation with a new message.

### Backend Behavior

Two ways to stop and resume:

**Way 1: Explicit stop, then send message**

```
POST /api/sessions/{id}/stop  →  session status becomes "cancelled"
                                  ↓
WS user_message               →  session auto-resumes with new message
```

**Way 2: Send message directly (auto-stop)**

```
WS user_message (while session is "running")
  → backend auto-writes cancel.signal
  → waits ~1s for old runtime to stop
  → starts new runtime with user's message
```

In both cases, the conversation continues seamlessly — all previous messages are preserved, the new message is appended, and the LLM responds.

### Session Status Values

| Status | Meaning | User can send message? |
|--------|---------|----------------------|
| `running` | Agent is actively processing | Yes — backend auto-stops old run first |
| `cancelled` | Stopped by user | Yes — auto-resumes |
| `completed` | Finished normally | Yes — continues conversation |
| `failed` | Crashed with error | Yes — retries from last state |
| `interrupted` | Stale (no activity >5min) | Yes — resumes |
| `waiting_for_human` | Waiting for HITL decision | No — must resolve HITL first |

### API Reference

#### Stop a Session

```
POST /api/sessions/{session_id}/stop
```

Query params:
- `force` (boolean, default `false`) — force-kill child agents too

Response:
```json
{"status": "cancelled", "force": false, "session_id": "..."}
```

#### WebSocket Events

When a session is stopped, the server broadcasts:

```json
{"type": "session_end", "session_id": "...", "stopped": true}
```

When a new message triggers auto-stop of a running session, the server:
1. Broadcasts `session_end` (stopped=true) for the old run
2. Starts a new run, broadcasting events as usual (`text_delta`, `tool_call_start`, etc.)

### Recommended UI Implementation

#### Stop Button

- Show a **Stop** button whenever session status is `running`
- On click: `POST /api/sessions/{session_id}/stop`
- After receiving `session_end` event, update UI to show session is stopped
- The message input should remain active — user can send a new message to resume

#### Auto-Resume via Message

- The message input should always be enabled (except during `waiting_for_human` with pending HITL)
- When user sends a message while the session is `running`, the backend handles stop+resume automatically
- UI does not need to call `/stop` first — just send the `user_message` via WebSocket
- Show a brief loading state while the backend stops the old run (~1s)

#### Status Indicators

```
running          →  "Agent is thinking..."  + [Stop] button
cancelled        →  "Stopped"               + message input active
completed        →  "Completed"             + message input active
failed           →  "Error"                 + message input active
interrupted      →  "Interrupted"           + message input active
waiting_for_human → "Waiting for approval"  + HITL resolve UI
```

---

## 2. Workspace Files API

### Problem

Agents produce files during execution (reports, CSVs, images, etc.) stored in the session workspace. Users need to view and download these files.

### Endpoints

#### List Files

```
GET /api/sessions/{session_id}/files?path={subdir}
```

- `path` is optional, defaults to workspace root
- Returns file/directory listing

Response:
```json
{
  "files": [
    {
      "name": "report.csv",
      "type": "file",
      "size": 10240,
      "modified_at": "2026-03-04T10:00:00+00:00"
    },
    {
      "name": "output",
      "type": "directory",
      "size": 0,
      "modified_at": "2026-03-04T09:30:00+00:00"
    }
  ],
  "path": ""
}
```

- Empty `files` array when workspace has no files (not an error)
- `type` is either `"file"` or `"directory"`
- `size` is in bytes (0 for directories)
- `modified_at` is ISO 8601 UTC

#### Download / Preview File

```
GET /api/sessions/{session_id}/files/{file_path}
```

- Returns the file with auto-detected `Content-Type` (e.g., `text/csv`, `image/png`, `application/json`)
- Add `?download=true` to force download (sets `Content-Disposition: attachment`)

Examples:
```
GET /api/sessions/abc123/files/report.csv           → inline (Content-Type: text/csv)
GET /api/sessions/abc123/files/report.csv?download=true → download
GET /api/sessions/abc123/files/output/chart.png     → inline image
GET /api/sessions/abc123/files/sub/data.json        → JSON response
```

Error responses:
- `404` — session or file not found
- `403` — path traversal attempt (e.g., `../`)

### Recommended UI Implementation

#### File List in Session Detail

- After session completes (or while running), call `GET /api/sessions/{id}/files`
- If `files` array is non-empty, show a "Files" section/tab in the session detail view
- For directories, allow clicking to navigate (call the same endpoint with `?path=dirname`)
- Show file size in human-readable format (KB, MB)

#### File Actions

| File Type | Action |
|-----------|--------|
| Images (`.png`, `.jpg`, `.svg`) | Inline preview with `<img src="/api/sessions/{id}/files/{path}">` |
| Text/JSON/CSV | Inline preview in code block or table |
| Other | Download button linking to `?download=true` |

#### File Download

Direct link or `fetch`:

```javascript
// Download link
const url = `/api/sessions/${sessionId}/files/${filePath}?download=true`;
window.open(url);

// Or fetch with auth
const resp = await fetch(`/api/sessions/${sessionId}/files/${filePath}`);
const blob = await resp.blob();
```

Auth is handled by the existing cookie/session — no extra headers needed for browser requests.

#### Polling for New Files

During a running session, the workspace may grow as the agent produces files. Options:
- Poll `GET /api/sessions/{id}/files` periodically (e.g., every 5s while session is running)
- Or refresh the file list when `session_end` event is received
