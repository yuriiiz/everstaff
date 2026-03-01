"""CLI entry point for the agent framework."""
from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

from everstaff.core.config import load_config
from everstaff.utils.logging import setup_logging


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="agent",
        description="Run AI agents from YAML definitions",
    )
    subparsers = parser.add_subparsers(dest="command")

    parser.add_argument("--verbose", "-v", action="store_true", help="Enable DEBUG logging")

    # agent run
    run_parser = subparsers.add_parser("run", help="Run an agent interactively")
    run_parser.add_argument("yaml_path", help="Path to agent YAML definition")
    run_parser.add_argument("--config", help="Path to framework config directory")
    run_parser.add_argument("--model-override", help="Override the model (LiteLLM string)")
    run_parser.add_argument(
        "--trace", choices=["console", "none"], default="console",
        help="Tracing backend (default: console)",
    )
    run_parser.add_argument("--single", metavar="MESSAGE", help="Single message mode")
    run_parser.add_argument("--resume", metavar="SESSION_ID", help="Resume a previous session")

    # agent info
    info_parser = subparsers.add_parser("info", help="Show agent info")
    info_parser.add_argument("yaml_path", help="Path to agent YAML definition")
    info_parser.add_argument("--config", help="Path to framework config directory")

    # agent skills
    skills_parser = subparsers.add_parser("skills", help="Manage skills")
    skills_sub = skills_parser.add_subparsers(dest="skills_command")
    skills_list_parser = skills_sub.add_parser("list", help="List all discovered skills")
    skills_list_parser.add_argument("--config", help="Path to framework config directory")

    # agent init
    init_parser = subparsers.add_parser("init", help="Initialize a new Agent OS project in the current directory")
    init_parser.add_argument("--name", help="Project name (default: directory name)")
    init_parser.add_argument("--force", action="store_true", help="Overwrite existing files")

    # agent sessions
    sessions_parser = subparsers.add_parser("sessions", help="Manage sessions")
    sessions_parser.add_argument("--config", help="Path to framework config directory")
    sessions_sub = sessions_parser.add_subparsers(dest="sessions_command")
    sessions_sub.add_parser("list", help="List saved sessions")
    sessions_show = sessions_sub.add_parser("show", help="Show a session's history")
    sessions_show.add_argument("session_id", help="Session ID to show")

    args = parser.parse_args()

    log_level = "DEBUG" if getattr(args, "verbose", False) else "INFO"
    setup_logging(console=True, level=log_level)

    if args.command == "init":
        _init_project(args)
    elif args.command == "run":
        asyncio.run(_run_agent(args))
    elif args.command == "info":
        asyncio.run(_show_info(args))
    elif args.command == "skills":
        asyncio.run(_handle_skills(args))
    elif args.command == "sessions":
        asyncio.run(_handle_sessions(args))
    else:
        parser.print_help()


def _init_project(args: argparse.Namespace) -> None:
    from everstaff.scaffold import init_project

    target = Path.cwd()
    name = args.name or target.name
    created = init_project(target, name, force=args.force)
    if not created:
        print("All files already exist. Use --force to overwrite.")
        return
    for f in created:
        print(f"  created {f}")
    print(f"\nProject '{name}' initialized. Run 'uv sync && uv run python main.py' to start.")


async def _run_agent(args: argparse.Namespace) -> None:
    from everstaff.builder.agent_builder import AgentBuilder
    from everstaff.builder.environment import DefaultEnvironment
    from everstaff.core.factories import build_file_store, build_channel_manager
    from everstaff.schema.agent_spec import AgentSpec
    from everstaff.utils.yaml_loader import load_yaml

    config = load_config(args.config)
    yaml_data = load_yaml(args.yaml_path)
    spec = AgentSpec(**yaml_data)

    if args.model_override:
        spec.model_override = args.model_override

    # Build channels from config (Lark WS, etc.) so HITL cards are sent in CLI mode too
    file_store = build_file_store(config.storage, str(config.sessions_dir))
    channel_manager = build_channel_manager(config, file_store)
    await channel_manager.start_all()

    env = DefaultEnvironment(
        sessions_dir=str(config.sessions_dir),
        session_id=args.resume,
        config=config,
        channel_manager=channel_manager,
    )

    runtime, context = await AgentBuilder(spec, env).build()

    if args.single:
        from everstaff.protocols import HumanApprovalRequired
        try:
            result = await runtime.run(args.single)
            print(result)
        except HumanApprovalRequired:
            print("[HITL requested — session paused. Use POST /hitl/resolve or run interactively to continue.]")
        finally:
            await context.aclose()
            await channel_manager.stop_all()
        return

    print(f"Agent '{spec.agent_name}' ready.")
    print(f"Session: {context.session_id}")
    print("Type 'exit' or 'quit' to end.\n")

    try:
        while True:
            try:
                user_input = input("You: ")
            except (EOFError, KeyboardInterrupt):
                break
            if user_input.strip().lower() in ("exit", "quit"):
                break
            if not user_input.strip():
                continue
            try:
                from everstaff.protocols import HumanApprovalRequired
                try:
                    response = await runtime.run(user_input)
                    print(f"\nAgent: {response}\n")
                except HumanApprovalRequired as hitl_exc:
                    sessions_dir_path = Path(config.sessions_dir).expanduser().resolve()
                    await _handle_cli_hitl(
                        hitl_requests=hitl_exc.requests,
                        session_id=context.session_id,
                        agent_name=spec.agent_name,
                        sessions_dir=sessions_dir_path,
                        config=config,
                        channel_manager=channel_manager,
                    )
            except Exception as e:
                print(f"\nError: {e}\n", file=sys.stderr)
    finally:
        await context.aclose()
        await channel_manager.stop_all()


async def _handle_cli_hitl(
    hitl_requests: list,
    session_id: str,
    agent_name: str,
    sessions_dir,
    config,
    channel_manager=None,
) -> None:
    """Interactively collect human decisions for HITL request(s) and resume the session."""
    import json
    from pathlib import Path
    from datetime import datetime, timezone
    import everstaff.api.sessions as _sessions_mod

    session_path = Path(sessions_dir) / session_id / "session.json"
    if not session_path.exists():
        print(f"\n[HITL] Could not find session.json for session {session_id}")
        return

    session_data = json.loads(session_path.read_text())

    for hitl_req in hitl_requests:
        req_type = hitl_req.type
        prompt = hitl_req.prompt
        context = hitl_req.context
        options = hitl_req.options or []

        print("\n" + "=" * 60)
        print("Agent needs human input:")
        print(f"  Type   : {req_type}")
        print(f"  Prompt : {prompt}")
        if context:
            print(f"  Context: {context}")
        if options and req_type != "choose":
            print(f"  Options: {', '.join(options)}")
        print("=" * 60)

        if req_type == "approve_reject":
            try:
                decision = input("Your decision [approve/reject]: ").strip()
                comment_raw = input("Comment (optional, press Enter to skip): ").strip()
                comment = comment_raw if comment_raw else None
            except (EOFError, KeyboardInterrupt):
                print("\n[HITL] Cancelled.")
                return
        elif req_type == "choose":
            print("\nOptions:")
            for i, opt in enumerate(options, 1):
                print(f"  {i}. {opt}")
            print()
            try:
                raw = input(f"Enter number(s) [1-{len(options)}], comma-separated: ").strip()
                comment_raw = input("Comment (optional, press Enter to skip): ").strip()
                comment = comment_raw if comment_raw else None
            except (EOFError, KeyboardInterrupt):
                print("\n[HITL] Cancelled.")
                return
            selected_texts = []
            for part in raw.split(","):
                part = part.strip()
                if part.isdigit():
                    idx = int(part) - 1
                    if 0 <= idx < len(options):
                        selected_texts.append(options[idx])
            decision = ", ".join(selected_texts) if selected_texts else raw
        else:
            try:
                decision = input("Your response: ").strip()
                comment_raw = input("Comment (optional, press Enter to skip): ").strip()
                comment = comment_raw if comment_raw else None
            except (EOFError, KeyboardInterrupt):
                print("\n[HITL] Cancelled.")
                return

        # Update the HITL request in session.json
        for item in session_data.get("hitl_requests", []):
            if item.get("hitl_id") == hitl_req.hitl_id:
                item["status"] = "resolved"
                item["response"] = {
                    "decision": decision,
                    "comment": comment,
                    "resolved_at": datetime.now(timezone.utc).isoformat(),
                    "resolved_by": "cli",
                }
                break

    session_path.write_text(json.dumps(session_data, ensure_ascii=False, indent=2))

    print("\nResuming session...\n")
    await _sessions_mod._resume_session_task(
        session_id, agent_name, "", config,
        channel_manager=channel_manager,
    )


async def _show_info(args: argparse.Namespace) -> None:
    from everstaff.schema.agent_spec import AgentSpec
    from everstaff.skills.manager import SkillManager
    from everstaff.utils.yaml_loader import load_yaml

    config = load_config(args.config)
    yaml_data = load_yaml(args.yaml_path)
    spec = AgentSpec(**yaml_data)

    print(f"Agent: {spec.agent_name}")
    print(f"Version: {spec.version}")
    print(f"Description: {spec.description}")

    if spec.skills:
        print(f"Skills: {', '.join(spec.skills)}")
        mgr = SkillManager(config.skills_dirs)
        for meta in mgr.list():
            if meta.name in spec.skills:
                print(f"  ✓ {meta.name}: {meta.description}")

    if spec.sub_agents:
        print("Sub-agents:")
        for name, sa in spec.sub_agents.items():
            print(f"  - {name}: {sa.description}")


async def _handle_skills(args: argparse.Namespace) -> None:
    from everstaff.skills.manager import SkillManager

    if args.skills_command == "list":
        config = load_config(args.config)
        mgr = SkillManager(config.skills_dirs)
        skills = mgr.list()
        if not skills:
            print("No skills found.")
            return
        print(f"Discovered {len(skills)} skill(s):\n")
        for meta in skills:
            print(f"  {meta.name}")
            print(f"    {meta.description}")
            print(f"    Path: {meta.path}")
            print()
    else:
        print("Usage: agent skills list")


async def _handle_sessions(args: argparse.Namespace) -> None:
    from everstaff.memory.file_store import FileMemoryStore

    config = load_config(args.config)
    store = FileMemoryStore(base_dir=config.sessions_dir)

    if args.sessions_command == "list":
        sessions_dir = Path(config.sessions_dir)
        if not sessions_dir.exists():
            print("No saved sessions found.")
            return
        files = sorted(sessions_dir.glob("*.json"))
        if not files:
            print("No saved sessions found.")
            return
        print(f"Saved sessions ({len(files)}):\n")
        for f in files:
            messages = await store.load(f.stem)
            print(f"  {f.stem}  ({len(messages)} messages)")

    elif args.sessions_command == "show":
        messages = await store.load(args.session_id)
        if not messages:
            print(f"Session not found: {args.session_id}")
            return
        print(f"Session: {args.session_id}  ({len(messages)} messages)\n")
        for msg in messages:
            role = msg.role.upper()
            content = msg.content or ""
            if msg.tool_calls:
                tools = ", ".join(tc["function"]["name"] for tc in msg.tool_calls)
                content += f" [calls: {tools}]"
            print(f"  [{role}] {content[:200]}")

    else:
        print("Usage: agent sessions [list|show]")
