"""Native tool: request_human_input — raises HumanApprovalRequired to pause the session."""
from __future__ import annotations

import logging
from typing import Any
from uuid import uuid4

from everstaff.protocols import HitlRequest, HumanApprovalRequired, ToolDefinition, ToolResult

logger = logging.getLogger(__name__)

# Valid HITL tool modes (mirrors hitl_mode in AgentSpec, minus "never")
_VALID_MODES = ("on_request", "notify")


class RequestHumanInputTool:
    name = "request_human_input"

    def __init__(
        self,
        channel_manager: Any = None,
        session_id: str = "",
        mode: str = "on_request",
    ) -> None:
        """
        Parameters
        ----------
        channel_manager:
            Optional ChannelManager instance used to send notify-type requests
            to channels without blocking the session.
        session_id:
            Session identifier forwarded to channel_manager.broadcast().
        mode:
            "on_request" — full HITL: agent decides when to ask human.
            "notify"     — notify-only: non-blocking notifications, no blocking.
        """
        if mode not in _VALID_MODES:
            raise ValueError(f"Invalid HITL mode: {mode!r}, expected one of {_VALID_MODES}")
        self._channel_manager = channel_manager
        self._session_id = session_id
        self._mode = mode

    @property
    def definition(self) -> ToolDefinition:
        if self._mode == "notify":
            return self._notify_definition()
        return self._full_definition()

    def _full_definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="request_human_input",
            description=(
                "Pause this session and request human input before continuing. "
                "You MUST call this tool whenever you need information, confirmation, or a decision from the human. "
                "NEVER ask questions or request feedback in your response text — always use this tool instead.\n"
                "Types:\n"
                "- 'approve_reject': yes/no decision\n"
                "- 'choose': human picks from provided options list\n"
                "- 'provide_input': human provides free-text response\n"
                "- 'notify': send a non-blocking notification to the user (no pause)"
            ),
            parameters={
                "type": "object",
                "properties": {
                    "prompt": {
                        "type": "string",
                        "description": "The question or description of what is needed from the human",
                    },
                    "type": {
                        "type": "string",
                        "enum": ["approve_reject", "choose", "provide_input", "notify"],
                        "description": "The kind of human input required",
                    },
                    "options": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "For 'choose' type: the list of options for the human to pick from",
                    },
                    "context": {
                        "type": "string",
                        "description": "Additional context to help the human make the decision",
                    },
                    "timeout": {
                        "type": "integer",
                        "description": "Timeout in seconds. Default 86400 (1 day). After timeout the request expires.",
                    },
                },
                "required": ["prompt", "type"],
            },
        )

    def _notify_definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="request_human_input",
            description=(
                "Send a non-blocking notification to the human. "
                "Use this to inform the user about progress, results, or important events. "
                "This does NOT pause the session — execution continues immediately after sending."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "prompt": {
                        "type": "string",
                        "description": "The notification message to send to the human",
                    },
                    "context": {
                        "type": "string",
                        "description": "Additional context for the notification",
                    },
                },
                "required": ["prompt"],
            },
        )

    def get_prompt_injection(self) -> str:
        if self._mode == "notify":
            return (
                "## Human Notification Rules\n\n"
                "You have access to the `request_human_input` tool in **notify-only** mode. "
                "You can send non-blocking notifications to the human but you CANNOT pause "
                "execution to wait for a response.\n\n"
                "**When to use it:**\n"
                "- Report progress on long-running tasks\n"
                "- Inform the user of important results or events\n"
                "- Alert about warnings or issues encountered\n\n"
                "**Important:** This tool only sends notifications. "
                "You cannot ask questions or request decisions — proceed autonomously."
            )
        return (
            "## Human Interaction Rules\n\n"
            "You have access to the `request_human_input` tool. Use it ONLY when you "
            "genuinely need information, a decision, or clarification that you cannot determine "
            "from the conversation context.\n\n"
            "**When to use it:**\n"
            "- You need a decision the human hasn't made yet (e.g. which option to pick)\n"
            "- You lack information required to proceed (e.g. a file path, a preference)\n"
            "- The task is ambiguous and you need clarification\n\n"
            "**When NOT to use it:**\n"
            "- The human gave you a clear, direct instruction — just execute it\n"
            "- You already have all the information needed to complete the task\n"
            "- You want to \"confirm\" an action that was explicitly requested\n\n"
            "When you do need human input, NEVER ask questions in your response text. "
            "Call `request_human_input` with the appropriate type "
            "(approve_reject, choose, provide_input, or notify). "
            "Asking questions in your content without calling this tool is a critical error — "
            "the human will NOT receive your message and the session will stall."
        )

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        req_type = args.get("type", "notify") if self._mode == "notify" else args["type"]

        # In notify-only mode, force type to "notify" regardless of what LLM sends
        if self._mode == "notify":
            req_type = "notify"

        hitl_request = HitlRequest(
            hitl_id=str(uuid4()),
            type=req_type,
            prompt=args["prompt"],
            options=args.get("options", []),
            context=args.get("context", ""),
            timeout_seconds=args.get("timeout", 86400),
        )

        if hitl_request.type == "notify":
            # Non-blocking notification — send to channels and continue without pausing.
            if self._channel_manager is not None:
                try:
                    await self._channel_manager.broadcast(self._session_id, hitl_request)
                except Exception as exc:
                    logger.warning("Notify HITL broadcast failed: %s", exc)
            return ToolResult(tool_call_id="", content="Notification sent")

        raise HumanApprovalRequired([hitl_request])
