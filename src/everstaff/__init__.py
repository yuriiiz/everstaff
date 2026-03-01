"""everstaff — An open-source platform for autonomous AI agents.

Public API:
    load_config(config_dir=None, *, skills_dirs=None, ...) -> FrameworkConfig
    create_app(config_dir=None, *, skills_dirs=None, ...) -> FastAPI
    run_cli() -> None
"""
from __future__ import annotations

__version__ = "0.1.0"

__all__ = ["__version__", "load_config", "create_app", "run_cli"]


def load_config(
    config_dir=None,
    *,
    skills_dirs=None,
    tools_dirs=None,
    agents_dir=None,
    sessions_dir=None,
):
    """Load framework configuration.

    Args:
        config_dir: If given, read config.yaml from this directory only
                    (full override, no merging).
        skills_dirs: Additional skills directories to append (merge mode only).
        tools_dirs:  Additional tools directories to append (merge mode only).
        agents_dir:  Override agents directory (merge mode only).
        sessions_dir: Override sessions directory (merge mode only).

    Returns:
        FrameworkConfig instance.
    """
    from everstaff.core.config import load_config as _load
    return _load(
        config_dir,
        skills_dirs=skills_dirs,
        tools_dirs=tools_dirs,
        agents_dir=agents_dir,
        sessions_dir=sessions_dir,
    )


def create_app(
    config_dir=None,
    *,
    skills_dirs=None,
    tools_dirs=None,
    agents_dir=None,
    sessions_dir=None,
):
    """Create and return a FastAPI application.

    Args:
        config_dir: If given, read config from this directory only.
        skills_dirs: Additional skills dirs (appended, merge mode only).
        tools_dirs:  Additional tools dirs (appended, merge mode only).
        agents_dir:  Override agents dir (merge mode only).
        sessions_dir: Override sessions dir (merge mode only).

    Returns:
        FastAPI app — run with ``uvicorn.run(app, ...)``.

    Example::

        import everstaff, uvicorn
        app = everstaff.create_app(config_dir="./config")
        uvicorn.run(app, host="0.0.0.0", port=8000)
    """
    cfg = load_config(
        config_dir,
        skills_dirs=skills_dirs,
        tools_dirs=tools_dirs,
        agents_dir=agents_dir,
        sessions_dir=sessions_dir,
    )
    from everstaff.api import create_app as _create_app
    return _create_app(config=cfg)


def run_cli() -> None:
    """Run the agent CLI (equivalent to the ``agent`` command)."""
    from everstaff.cli import main
    main()
