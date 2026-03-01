"""Sub-agent specification models."""

# SubAgentSpec is defined in schema/agent_spec.py
# This module re-exports it and adds any agent-specific helpers.

from everstaff.schema.agent_spec import SubAgentSpec

__all__ = ["SubAgentSpec"]
