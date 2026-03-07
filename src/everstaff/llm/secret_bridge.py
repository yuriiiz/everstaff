"""Bridge SecretStore to litellm's secret manager interface."""
from __future__ import annotations

import logging
import os
from typing import Optional, Union, TYPE_CHECKING

import httpx
import litellm
from litellm.integrations.custom_secret_manager import CustomSecretManager
from litellm.types.secret_managers.main import KeyManagementSystem, KeyManagementSettings

if TYPE_CHECKING:
    from everstaff.core.secret_store import SecretStore


class _SecretFallbackFilter(logging.Filter):
    """Suppress litellm ERROR logs for expected secret fallbacks."""

    def filter(self, record: logging.LogRecord) -> bool:
        return "Defaulting to os.environ" not in record.getMessage()


class SecretStoreBridge(CustomSecretManager):
    """litellm CustomSecretManager backed by everstaff SecretStore.

    Falls back to os.environ for non-secret config keys (e.g.
    USE_LITELLM_PROXY) so litellm doesn't log noisy ERROR tracebacks.
    """

    def __init__(self, secret_store: "SecretStore") -> None:
        super().__init__(secret_manager_name="everstaff")
        self._store = secret_store

    def _read(self, secret_name: str) -> Optional[str]:
        value = self._store.get(secret_name)
        if value is None:
            value = os.environ.get(secret_name)
        return value

    async def async_read_secret(
        self,
        secret_name: str,
        optional_params: Optional[dict] = None,
        timeout: Optional[Union[float, httpx.Timeout]] = None,
    ) -> Optional[str]:
        return self._read(secret_name)

    def sync_read_secret(
        self,
        secret_name: str,
        optional_params: Optional[dict] = None,
        timeout: Optional[Union[float, httpx.Timeout]] = None,
    ) -> Optional[str]:
        return self._read(secret_name)


def install_secret_bridge(secret_store: "SecretStore") -> None:
    """Register SecretStore as litellm's secret provider."""
    litellm.secret_manager_client = SecretStoreBridge(secret_store)
    litellm._key_management_system = KeyManagementSystem.CUSTOM
    litellm._key_management_settings = KeyManagementSettings(access_mode="read_only")
    # Suppress noisy "Defaulting to os.environ" ERROR logs from litellm
    # when querying config keys (e.g. USE_LITELLM_PROXY) not in SecretStore.
    logging.getLogger("LiteLLM").addFilter(_SecretFallbackFilter())
