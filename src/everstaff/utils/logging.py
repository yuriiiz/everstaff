"""Unified logging setup for everstaff.

Call setup_logging() once at process startup (in cli.py or server.py).
All modules use standard `logging.getLogger(__name__)` — no changes needed there.

Log format includes timestamp, level, logger name and message so every
log line is fully traceable even in production.
"""
from __future__ import annotations

import logging
import sys
from pathlib import Path

_configured = False

_FMT = "%(asctime)s %(levelname)-8s %(name)s — %(message)s"
_DATE_FMT = "%Y-%m-%dT%H:%M:%S"

# Chatty stdlib and third-party loggers to suppress at DEBUG/INFO — cap at WARNING.
_NOISY_LOGGERS = [
    "httpx",
    "httpcore",
    "litellm",
    "urllib3",
    "asyncio",
    "multipart",
    "uvicorn.access",  # keep error/warning, suppress access log spam
]

_LITELLM_LOGGERS = ["LiteLLM", "LiteLLM Router", "LiteLLM Proxy"]

# Loggers that install their own handlers/formatters — we clear handlers
# and force propagation so they use our root formatter instead.
_HIJACKED_LOGGERS = [
    *_NOISY_LOGGERS,
    *_LITELLM_LOGGERS,
    "uvicorn",
    "uvicorn.error",
]


def setup_logging(
    *,
    console: bool = True,
    file: str | None = None,
    level: str = "INFO",
) -> None:
    """Configure the root logger. Safe to call multiple times (idempotent).

    Args:
        console: Emit logs to stderr (always use stderr so stdout stays clean
                 for agent output).
        file:    Path to a log file. Rotated externally (use logrotate / systemd).
                 If None, no file handler is added.
        level:   Root log level string ("DEBUG", "INFO", "WARNING", "ERROR").
    """
    numeric_level = getattr(logging, level.upper(), None)
    if not isinstance(numeric_level, int):
        raise ValueError(f"Unknown log level: {level!r}")

    global _configured
    if _configured:
        return
    _configured = True
    root = logging.getLogger()
    root.setLevel(numeric_level)

    formatter = logging.Formatter(_FMT, datefmt=_DATE_FMT)

    if console:
        handler = logging.StreamHandler(sys.stderr)
        handler.setFormatter(formatter)
        handler.setLevel(numeric_level)
        root.addHandler(handler)

    if file:
        log_path = Path(file)
        log_path.parent.mkdir(parents=True, exist_ok=True)
        fh = logging.FileHandler(log_path, encoding="utf-8")
        fh.setFormatter(formatter)
        fh.setLevel(numeric_level)
        root.addHandler(fh)

    _hijack_third_party_loggers()


def _hijack_third_party_loggers() -> None:
    """Clear handlers from third-party loggers and force propagation to root."""
    for name in _HIJACKED_LOGGERS:
        lib_logger = logging.getLogger(name)
        lib_logger.handlers.clear()
        lib_logger.propagate = True

    # Cap chatty loggers at WARNING (uvicorn stays at root level for startup msgs)
    for name in [*_NOISY_LOGGERS, *_LITELLM_LOGGERS]:
        logging.getLogger(name).setLevel(logging.WARNING)


def reclaim_loggers() -> None:
    """Re-apply handler cleanup after frameworks (e.g. uvicorn) reconfigure logging.

    Call this from app lifespan startup to ensure uvicorn's handlers are replaced.
    """
    _hijack_third_party_loggers()
