"""Sandbox process entry point.

This module is the main() for a sandbox subprocess. It:
1. Connects to orchestrator via IPC channel
2. Authenticates with ephemeral token and receives secrets
3. Builds SandboxEnvironment with proxy adapters
4. Runs AgentRuntime with the provided agent spec
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from pathlib import Path

from everstaff.core.secret_store import SecretStore
from everstaff.sandbox.environment import SandboxEnvironment
from everstaff.sandbox.ipc.unix_socket import UnixSocketChannel

logger = logging.getLogger(__name__)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Everstaff sandbox process")
    parser.add_argument("--socket-path", required=True, help="IPC socket path")
    parser.add_argument("--token", required=True, help="Ephemeral auth token")
    parser.add_argument("--session-id", required=True, help="Session ID")
    parser.add_argument("--agent-spec", required=True, help="Agent spec JSON string")
    parser.add_argument("--workspace-dir", default="/work", help="Workspace directory")
    return parser.parse_args(argv)


async def sandbox_main(
    socket_path: str,
    token: str,
    session_id: str,
    agent_spec_json: str,
    workspace_dir: str,
) -> None:
    """Entry point for sandbox process."""
    # 1. Connect and authenticate
    channel = UnixSocketChannel()
    await channel.connect(socket_path)

    try:
        auth_result = await channel.send_request("auth", {"token": token})
        secret_store = SecretStore(auth_result.get("secrets", {}))

        # 2. Build environment
        workspace = Path(workspace_dir)
        workspace.mkdir(parents=True, exist_ok=True)
        env = SandboxEnvironment(
            channel=channel,
            secret_store=secret_store,
            workspace_dir=workspace,
        )

        # 3. Register cancel handler
        _cancelled = asyncio.Event()

        async def _on_cancel(params):
            _cancelled.set()

        channel.on_push("cancel", _on_cancel)

        # 4. Register HITL resolution handler
        _hitl_resolutions: asyncio.Queue = asyncio.Queue()

        async def _on_hitl_resolution(params):
            _hitl_resolutions.put_nowait(params)

        channel.on_push("hitl.resolution", _on_hitl_resolution)

        # 5. Run agent
        await _run_agent(
            env=env,
            session_id=session_id,
            agent_spec_json=agent_spec_json,
            cancelled=_cancelled,
            hitl_resolutions=_hitl_resolutions,
        )
    finally:
        await channel.close()


async def _run_agent(
    env: SandboxEnvironment,
    session_id: str,
    agent_spec_json: str,
    cancelled: asyncio.Event,
    hitl_resolutions: asyncio.Queue,
) -> None:
    """Build and run AgentRuntime. Separated for testability."""
    from everstaff.builder.agent_builder import AgentBuilder
    from everstaff.schema.agent_spec import AgentSpec

    spec = AgentSpec.model_validate_json(agent_spec_json)
    builder = AgentBuilder(spec, env, session_id=session_id)
    runtime, ctx = await builder.build()

    async for _event in runtime.run_stream():
        pass  # All saves/traces go through proxies automatically


def main() -> None:
    """CLI entry point: python -m everstaff.sandbox.entry"""
    args = parse_args()
    asyncio.run(sandbox_main(
        socket_path=args.socket_path,
        token=args.token,
        session_id=args.session_id,
        agent_spec_json=args.agent_spec,
        workspace_dir=args.workspace_dir,
    ))


if __name__ == "__main__":
    main()
