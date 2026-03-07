"""Tests for self-mutation tools with HITL guard."""
import pytest
import yaml
from pathlib import Path

from everstaff.daemon.mutation_tools import (
    validate_no_permission_mutation,
    PermissionMutationForbidden,
    build_mutation_hitl_request,
    apply_yaml_mutation,
)


def test_reject_permission_mutation():
    with pytest.raises(PermissionMutationForbidden):
        validate_no_permission_mutation({"permissions": {"allow": ["Bash"]}})


def test_reject_allow_field():
    with pytest.raises(PermissionMutationForbidden):
        validate_no_permission_mutation({"allow": ["Read"]})


def test_reject_deny_field():
    with pytest.raises(PermissionMutationForbidden):
        validate_no_permission_mutation({"deny": ["Bash(rm *)"]})


def test_accept_non_permission_change():
    validate_no_permission_mutation({"skills": ["new-skill"]})
    validate_no_permission_mutation({"instructions": "new instructions"})
    validate_no_permission_mutation({"mcp_servers": [{"name": "gh"}]})


def test_build_hitl_request():
    req = build_mutation_hitl_request(
        agent_name="bot",
        mutation_type="update_agent_skills",
        current_value=["skill-a"],
        proposed_value=["skill-a", "skill-b"],
        reasoning="need skill-b for code review",
    )
    assert req.type == "approve_reject"
    assert "skill-b" in req.prompt
    assert "bot" in req.prompt


def test_apply_yaml_mutation_skills(tmp_path):
    spec_path = tmp_path / "bot.yaml"
    spec_path.write_text(yaml.dump({
        "agent_name": "bot",
        "skills": ["skill-a"],
        "permissions": {"allow": ["Bash"]},
    }))
    apply_yaml_mutation(spec_path, "skills", ["skill-a", "skill-b"])
    updated = yaml.safe_load(spec_path.read_text())
    assert "skill-b" in updated["skills"]
    assert updated["permissions"]["allow"] == ["Bash"]


def test_apply_yaml_mutation_refuses_permissions(tmp_path):
    spec_path = tmp_path / "bot.yaml"
    spec_path.write_text(yaml.dump({"agent_name": "bot", "permissions": {"allow": []}}))
    with pytest.raises(PermissionMutationForbidden):
        apply_yaml_mutation(spec_path, "permissions", {"allow": ["*"]})
