"""Entry point — delegates to src/api."""
import os

from everstaff.utils.logging import setup_logging

_log_level = os.getenv("LOG_LEVEL", "INFO")
_log_file = os.getenv("LOG_FILE")
setup_logging(console=True, file=_log_file, level=_log_level)

from everstaff.api import create_app  # must import after logging is configured

app = create_app()
