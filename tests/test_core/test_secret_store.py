"""Tests for the in-memory SecretStore."""
import os
import pytest
from everstaff.core.secret_store import SecretStore


class TestSecretStore:
    def test_create_empty(self):
        store = SecretStore()
        assert store.get("ANY_KEY") is None
        assert store.as_dict() == {}

    def test_create_from_dict(self):
        store = SecretStore({"API_KEY": "sk-123", "DB_PASS": "secret"})
        assert store.get("API_KEY") == "sk-123"
        assert store.get("DB_PASS") == "secret"
        assert store.get("MISSING") is None

    def test_as_dict_returns_copy(self):
        store = SecretStore({"KEY": "val"})
        d = store.as_dict()
        d["KEY"] = "tampered"
        assert store.get("KEY") == "val"  # original unmodified

    def test_subset_returns_filtered_dict(self):
        store = SecretStore({"A": "1", "B": "2", "C": "3"})
        sub = store.subset(["A", "C"])
        assert sub == {"A": "1", "C": "3"}

    def test_subset_ignores_missing_keys(self):
        store = SecretStore({"A": "1"})
        sub = store.subset(["A", "MISSING"])
        assert sub == {"A": "1"}

    def test_from_environ_captures_snapshot(self):
        os.environ["_TEST_SECRET_STORE"] = "test_val"
        try:
            store = SecretStore.from_environ()
            assert store.get("_TEST_SECRET_STORE") == "test_val"
            # Changing os.environ after creation does not affect store
            os.environ["_TEST_SECRET_STORE"] = "changed"
            assert store.get("_TEST_SECRET_STORE") == "test_val"
        finally:
            os.environ.pop("_TEST_SECRET_STORE", None)

    def test_not_in_os_environ(self):
        """SecretStore does NOT leak into os.environ."""
        store = SecretStore({"PRIVATE": "secret"})
        assert os.environ.get("PRIVATE") is None

    def test_len(self):
        store = SecretStore({"A": "1", "B": "2"})
        assert len(store) == 2

    def test_contains(self):
        store = SecretStore({"A": "1"})
        assert "A" in store
        assert "B" not in store
