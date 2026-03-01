import pytest


def test_resolve_env_vars_plain_string_unchanged():
    from everstaff.core.config import _resolve_env_vars
    assert _resolve_env_vars("hello") == "hello"


def test_resolve_env_vars_substitutes_set_var(monkeypatch):
    from everstaff.core.config import _resolve_env_vars
    monkeypatch.setenv("MY_SECRET", "s3cr3t")
    assert _resolve_env_vars("${MY_SECRET}") == "s3cr3t"


def test_resolve_env_vars_inline_substitution(monkeypatch):
    from everstaff.core.config import _resolve_env_vars
    monkeypatch.setenv("DOMAIN", "feishu")
    assert _resolve_env_vars("open.${DOMAIN}.cn") == "open.feishu.cn"


def test_resolve_env_vars_raises_if_var_missing():
    from everstaff.core.config import _resolve_env_vars
    with pytest.raises(ValueError, match="MISSING_VAR"):
        _resolve_env_vars("${MISSING_VAR}")


def test_resolve_env_vars_dict_recursive(monkeypatch):
    from everstaff.core.config import _resolve_env_vars
    monkeypatch.setenv("APP_ID", "cli_x")
    monkeypatch.setenv("SECRET", "abc")
    result = _resolve_env_vars({"app_id": "${APP_ID}", "secret": "${SECRET}", "chat_id": "oc_grp"})
    assert result == {"app_id": "cli_x", "secret": "abc", "chat_id": "oc_grp"}


def test_resolve_env_vars_list_recursive(monkeypatch):
    from everstaff.core.config import _resolve_env_vars
    monkeypatch.setenv("V", "hello")
    assert _resolve_env_vars(["${V}", "world"]) == ["hello", "world"]


def test_resolve_env_vars_non_string_passthrough():
    from everstaff.core.config import _resolve_env_vars
    assert _resolve_env_vars(42) == 42
    assert _resolve_env_vars(True) is True
    assert _resolve_env_vars(None) is None


def test_channel_config_resolves_env_vars_on_load(monkeypatch, tmp_path):
    """End-to-end: channel config in YAML uses ${VAR}, gets resolved at load time."""
    import os
    from everstaff.core.config import load_config
    monkeypatch.setenv("LARK_APP_ID", "cli_resolved")
    monkeypatch.setenv("LARK_SECRET", "mysecret")
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".agent").mkdir()
    (tmp_path / ".agent" / "config.yaml").write_text(
        "channels:\n"
        "  lark-main:\n"
        "    type: lark\n"
        "    app_id: '${LARK_APP_ID}'\n"
        "    app_secret: '${LARK_SECRET}'\n"
        "    chat_id: oc_default\n"
    )
    cfg = load_config()
    assert cfg.channels["lark-main"].app_id == "cli_resolved"
    assert cfg.channels["lark-main"].app_secret == "mysecret"
