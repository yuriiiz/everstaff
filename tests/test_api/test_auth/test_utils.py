"""Tests for auth utility functions — expand_env_vars, matches_route."""

from __future__ import annotations

import pytest

from everstaff.api.auth.utils import expand_env_vars, matches_route


# ---------------------------------------------------------------------------
# expand_env_vars
# ---------------------------------------------------------------------------


class TestExpandEnvVars:
    def test_single_var(self, monkeypatch):
        monkeypatch.setenv("MY_SECRET", "hunter2")
        assert expand_env_vars("${MY_SECRET}") == "hunter2"

    def test_multiple_vars(self, monkeypatch):
        monkeypatch.setenv("HOST", "localhost")
        monkeypatch.setenv("PORT", "8080")
        assert expand_env_vars("http://${HOST}:${PORT}") == "http://localhost:8080"

    def test_no_vars(self):
        assert expand_env_vars("plain-string") == "plain-string"

    def test_missing_var_raises(self, monkeypatch):
        monkeypatch.delenv("DOES_NOT_EXIST", raising=False)
        with pytest.raises(ValueError, match="DOES_NOT_EXIST"):
            expand_env_vars("${DOES_NOT_EXIST}")

    def test_empty_string(self):
        assert expand_env_vars("") == ""

    def test_var_embedded_in_text(self, monkeypatch):
        monkeypatch.setenv("TOKEN", "abc123")
        assert expand_env_vars("Bearer ${TOKEN}") == "Bearer abc123"


# ---------------------------------------------------------------------------
# matches_route
# ---------------------------------------------------------------------------


class TestMatchesRoute:
    def test_exact_match(self):
        assert matches_route("/ping", ["/ping", "/docs"]) is True

    def test_exact_no_match(self):
        assert matches_route("/sessions", ["/ping", "/docs"]) is False

    def test_wildcard_match(self):
        assert matches_route("/webhooks/lark", ["/webhooks/*"]) is True

    def test_wildcard_match_deeper_path(self):
        assert matches_route("/webhooks/lark/events", ["/webhooks/*"]) is True

    def test_wildcard_no_match(self):
        assert matches_route("/sessions/123", ["/webhooks/*"]) is False

    def test_wildcard_exact_prefix(self):
        # The prefix itself (without trailing segment) should match
        assert matches_route("/webhooks/", ["/webhooks/*"]) is True

    def test_empty_patterns(self):
        assert matches_route("/ping", []) is False

    def test_mixed_patterns(self):
        patterns = ["/ping", "/docs", "/webhooks/*"]
        assert matches_route("/ping", patterns) is True
        assert matches_route("/webhooks/slack", patterns) is True
        assert matches_route("/sessions", patterns) is False
