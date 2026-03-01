"""_resume_session_task must pass session_id to AgentBuilder, not to DefaultEnvironment."""
import inspect
import re


def test_resume_session_task_passes_session_id_to_builder():
    """Verify _resume_session_task passes session_id to AgentBuilder."""
    from everstaff.api.sessions import _resume_session_task
    source = inspect.getsource(_resume_session_task)

    # Find the AgentBuilder constructor call and verify it has session_id=
    # Use a pattern that handles nested parentheses by matching balanced parens
    builder_match = re.search(r'AgentBuilder\((.+?)\)\.build\(\)', source, re.DOTALL)
    assert builder_match is not None, \
        "_resume_session_task must call AgentBuilder(...).build()"
    builder_args = builder_match.group(1)
    assert "session_id=" in builder_args, \
        f"AgentBuilder must receive session_id kwarg, got args: {builder_args}"


def test_default_environment_not_receiving_session_id_in_resume():
    """DefaultEnvironment in _resume_session_task should NOT receive session_id."""
    from everstaff.api.sessions import _resume_session_task
    source = inspect.getsource(_resume_session_task)

    # Extract the block between "DefaultEnvironment(" and the matching closing ")"
    # We need to handle nested parens like str(sessions_dir)
    start = source.find("DefaultEnvironment(")
    assert start != -1, "DefaultEnvironment call not found in _resume_session_task"
    # Walk forward from the opening paren counting depth
    paren_start = start + len("DefaultEnvironment")
    depth = 0
    end = paren_start
    for i, ch in enumerate(source[paren_start:], start=paren_start):
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
            if depth == 0:
                end = i + 1
                break
    env_call = source[start:end]
    assert "session_id" not in env_call, \
        f"DefaultEnvironment should not receive session_id, found: {env_call}"
