"""DefaultEnvironment.new_session_id must always generate fresh UUIDs."""
from everstaff.builder.environment import DefaultEnvironment


def test_new_session_id_always_fresh():
    """new_session_id() must generate a fresh UUID each time."""
    env = DefaultEnvironment(sessions_dir="/tmp/test")
    id1 = env.new_session_id()
    id2 = env.new_session_id()
    assert id1 != id2, "Each call to new_session_id() must return a different UUID"


def test_session_id_param_ignored():
    """Even when session_id is passed, new_session_id() should generate fresh UUIDs."""
    env = DefaultEnvironment(sessions_dir="/tmp/test", session_id="pinned-id")
    id1 = env.new_session_id()
    assert id1 != "pinned-id", "session_id param should be ignored (deprecated)"
    id2 = env.new_session_id()
    assert id2 != "pinned-id", "session_id param should be ignored (deprecated)"
    assert id1 != id2, "Each call must return a different UUID"
