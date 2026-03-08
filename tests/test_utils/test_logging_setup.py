"""Tests for the unified logging setup module."""
import logging

import pytest


@pytest.fixture(autouse=True)
def reset_logging_state():
    import everstaff.utils.logging as ul
    root = logging.getLogger()
    # Setup: clean state before each test
    ul._configured = False
    for h in root.handlers[:]:
        root.removeHandler(h)
        h.close()
    for name in ul._HIJACKED_LOGGERS:
        lg = logging.getLogger(name)
        lg.setLevel(logging.NOTSET)
        lg.handlers.clear()
        lg.propagate = True
    yield
    # Teardown: clean state after each test
    ul._configured = False
    for h in logging.getLogger().handlers[:]:
        logging.getLogger().removeHandler(h)
        h.close()
    for name in ul._HIJACKED_LOGGERS:
        lg = logging.getLogger(name)
        lg.setLevel(logging.NOTSET)
        lg.handlers.clear()
        lg.propagate = True


def test_setup_console_only(capsys):
    from everstaff.utils.logging import setup_logging
    setup_logging(console=True, level="DEBUG")

    logger = logging.getLogger("test.console")
    logger.info("hello console")

    captured = capsys.readouterr()
    assert "hello console" in captured.err  # logs go to stderr by default


def test_setup_file_only(tmp_path):
    log_file = tmp_path / "app.log"
    from everstaff.utils.logging import setup_logging
    setup_logging(console=False, file=str(log_file), level="INFO")

    logger = logging.getLogger("test.file")
    logger.info("hello file")
    logger.debug("should not appear")  # below INFO

    content = log_file.read_text()
    assert "hello file" in content
    assert "should not appear" not in content


def test_setup_both(tmp_path, capsys):
    log_file = tmp_path / "both.log"
    from everstaff.utils.logging import setup_logging
    setup_logging(console=True, file=str(log_file), level="WARNING")

    logger = logging.getLogger("test.both")
    logger.warning("dual output")
    logger.info("below threshold")

    captured = capsys.readouterr()
    file_content = log_file.read_text()

    assert "dual output" in captured.err
    assert "dual output" in file_content
    assert "below threshold" not in captured.err
    assert "below threshold" not in file_content


def test_setup_idempotent():
    """Calling setup_logging twice must not double-add handlers."""
    from everstaff.utils.logging import setup_logging
    setup_logging(console=True, level="INFO")
    setup_logging(console=True, level="INFO")

    root = logging.getLogger()
    # Exclude pytest's own LogCaptureHandler which is a StreamHandler subclass
    try:
        from _pytest.logging import LogCaptureHandler
        _pytest_handler_type = LogCaptureHandler
    except ImportError:
        _pytest_handler_type = ()
    console_handlers = [
        h for h in root.handlers
        if isinstance(h, logging.StreamHandler)
        and not isinstance(h, logging.FileHandler)
        and not isinstance(h, _pytest_handler_type)
    ]
    assert len(console_handlers) == 1


def test_third_party_noise_suppressed():
    """Noisy third-party loggers must be set to WARNING or higher by default."""
    from everstaff.utils.logging import setup_logging
    setup_logging(console=True, level="DEBUG")

    for name in ["httpx", "httpcore", "litellm", "urllib3", "asyncio"]:
        assert logging.getLogger(name).level >= logging.WARNING, (
            f"Logger '{name}' should be WARNING or higher to reduce noise"
        )


def test_invalid_level_raises():
    from everstaff.utils.logging import setup_logging
    with pytest.raises(ValueError, match="Unknown log level"):
        setup_logging(console=True, level="VERBOS")


def test_third_party_handlers_cleared():
    """Third-party loggers must have no own handlers and propagate=True."""
    # Pre-add a handler to simulate a third-party library configuring its own
    litellm_logger = logging.getLogger("LiteLLM")
    fake_handler = logging.StreamHandler()
    litellm_logger.addHandler(fake_handler)
    litellm_logger.propagate = False

    from everstaff.utils.logging import setup_logging
    setup_logging(console=True, level="INFO")

    # After setup, handler should be cleared and propagate restored
    assert len(litellm_logger.handlers) == 0
    assert litellm_logger.propagate is True

    # Also check one from _NOISY_LOGGERS
    httpx_logger = logging.getLogger("httpx")
    assert len(httpx_logger.handlers) == 0
    assert httpx_logger.propagate is True
