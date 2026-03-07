"""Tests for SecretStoreBridge."""
import pytest
from unittest.mock import patch
from everstaff.core.secret_store import SecretStore


class TestSecretStoreBridge:
    def test_sync_read_existing_key(self):
        from everstaff.llm.secret_bridge import SecretStoreBridge
        store = SecretStore({"OPENAI_API_KEY": "sk-test-123"})
        bridge = SecretStoreBridge(store)
        assert bridge.sync_read_secret("OPENAI_API_KEY") == "sk-test-123"

    def test_sync_read_missing_key_returns_none(self):
        from everstaff.llm.secret_bridge import SecretStoreBridge
        store = SecretStore({})
        bridge = SecretStoreBridge(store)
        assert bridge.sync_read_secret("MISSING_KEY") is None

    def test_falls_back_to_os_environ(self):
        from everstaff.llm.secret_bridge import SecretStoreBridge
        store = SecretStore({})
        bridge = SecretStoreBridge(store)
        with patch.dict("os.environ", {"SOME_CONFIG": "from_env"}):
            assert bridge.sync_read_secret("SOME_CONFIG") == "from_env"

    def test_secret_store_takes_precedence_over_environ(self):
        from everstaff.llm.secret_bridge import SecretStoreBridge
        store = SecretStore({"KEY": "from_store"})
        bridge = SecretStoreBridge(store)
        with patch.dict("os.environ", {"KEY": "from_env"}):
            assert bridge.sync_read_secret("KEY") == "from_store"

    @pytest.mark.asyncio
    async def test_async_read_existing_key(self):
        from everstaff.llm.secret_bridge import SecretStoreBridge
        store = SecretStore({"API_KEY": "val"})
        bridge = SecretStoreBridge(store)
        assert await bridge.async_read_secret("API_KEY") == "val"


class TestInstallSecretBridge:
    def test_install_configures_litellm(self):
        import litellm
        from everstaff.llm.secret_bridge import SecretStoreBridge, install_secret_bridge
        store = SecretStore({"KEY": "val"})

        old_client = litellm.secret_manager_client
        old_kms = litellm._key_management_system
        old_settings = litellm._key_management_settings
        try:
            install_secret_bridge(store)
            assert isinstance(litellm.secret_manager_client, SecretStoreBridge)
            assert litellm._key_management_system is not None
            assert litellm._key_management_settings is not None
        finally:
            litellm.secret_manager_client = old_client
            litellm._key_management_system = old_kms
            litellm._key_management_settings = old_settings
