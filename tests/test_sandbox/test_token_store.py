"""Tests for EphemeralTokenStore."""
import time
import pytest
from everstaff.sandbox.token_store import EphemeralTokenStore


class TestEphemeralTokenStore:
    def test_create_and_validate(self):
        store = EphemeralTokenStore()
        token = store.create("session-1", ttl_seconds=30)
        assert isinstance(token, str)
        assert len(token) > 16
        result = store.validate_and_consume(token)
        assert result == "session-1"

    def test_single_use(self):
        store = EphemeralTokenStore()
        token = store.create("session-1")
        assert store.validate_and_consume(token) == "session-1"
        assert store.validate_and_consume(token) is None  # already consumed

    def test_invalid_token(self):
        store = EphemeralTokenStore()
        assert store.validate_and_consume("nonexistent") is None

    def test_expired_token(self):
        store = EphemeralTokenStore()
        token = store.create("session-1", ttl_seconds=0)
        # TTL=0 means already expired
        time.sleep(0.01)
        assert store.validate_and_consume(token) is None

    def test_multiple_tokens(self):
        store = EphemeralTokenStore()
        t1 = store.create("session-1")
        t2 = store.create("session-2")
        assert t1 != t2
        assert store.validate_and_consume(t1) == "session-1"
        assert store.validate_and_consume(t2) == "session-2"

    def test_cleanup_expired(self):
        store = EphemeralTokenStore()
        store.create("old", ttl_seconds=0)
        store.create("new", ttl_seconds=300)
        time.sleep(0.01)
        store.cleanup_expired()
        assert len(store._tokens) == 1
