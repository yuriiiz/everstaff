"""Self-mutation tools — allow agents to modify their own config with HITL guard.

HARD CONSTRAINT: Any mutation touching permissions/allow/deny is FORBIDDEN.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import yaml

logger = logging.getLogger(__name__)

_FORBIDDEN_KEYS = frozenset({"permissions", "allow", "deny"})


class PermissionMutationForbidden(Exception):
    """Raised when a mutation attempts to change permission-related fields."""


def validate_no_permission_mutation(changes: dict[str, Any]) -> None:
    for key in changes:
        if key in _FORBIDDEN_KEYS:
            raise PermissionMutationForbidden(
                f"Mutation of '{key}' is forbidden. Permission fields cannot be self-modified."
            )


def build_mutation_hitl_request(
    *, agent_name: str, mutation_type: str,
    current_value: Any, proposed_value: Any, reasoning: str,
) -> Any:
    from everstaff.schema.hitl_models import HitlRequestPayload
    prompt = (
        f"Agent '{agent_name}' requests self-modification:\n\n"
        f"**Type:** {mutation_type}\n"
        f"**Reason:** {reasoning}\n\n"
        f"**Current value:**\n```\n{_format_value(current_value)}\n```\n\n"
        f"**Proposed value:**\n```\n{_format_value(proposed_value)}\n```\n\n"
        f"Approve this change?"
    )
    return HitlRequestPayload(type="approve_reject", prompt=prompt, context=f"Self-mutation: {mutation_type}")


def apply_yaml_mutation(spec_path: Path, field: str, value: Any) -> None:
    if field in _FORBIDDEN_KEYS:
        raise PermissionMutationForbidden(f"Cannot mutate '{field}' — permission fields are immutable.")
    data = yaml.safe_load(spec_path.read_text())
    data[field] = value
    spec_path.write_text(yaml.dump(data, default_flow_style=False, allow_unicode=True))


def _format_value(v: Any) -> str:
    if isinstance(v, (list, dict)):
        return yaml.dump(v, default_flow_style=False).strip()
    return str(v)
