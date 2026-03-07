"""Bridge SecretStore to litellm's secret manager interface."""
from __future__ import annotations

from typing import Optional, Union, TYPE_CHECKING

import httpx
import litellm
from litellm.integrations.custom_secret_manager import CustomSecretManager
from litellm.types.secret_managers.main import KeyManagementSystem, KeyManagementSettings

if TYPE_CHECKING:
    from everstaff.core.secret_store import SecretStore


class SecretStoreBridge(CustomSecretManager):
    """litellm CustomSecretManager backed by everstaff SecretStore."""

    def __init__(self, secret_store: "SecretStore") -> None:
        super().__init__(secret_manager_name="everstaff")
        self._store = secret_store

    async def async_read_secret(
        self,
        secret_name: str,
        optional_params: Optional[dict] = None,
        timeout: Optional[Union[float, httpx.Timeout]] = None,
    ) -> Optional[str]:
        return self._store.get(secret_name)

    def sync_read_secret(
        self,
        secret_name: str,
        optional_params: Optional[dict] = None,
        timeout: Optional[Union[float, httpx.Timeout]] = None,
    ) -> Optional[str]:
        return self._store.get(secret_name)


def install_secret_bridge(secret_store: "SecretStore") -> None:
    """Register SecretStore as litellm's secret provider."""
    litellm.secret_manager_client = SecretStoreBridge(secret_store)
    litellm._key_management_system = KeyManagementSystem.CUSTOM
    litellm._key_management_settings = KeyManagementSettings(access_mode="read_only")
