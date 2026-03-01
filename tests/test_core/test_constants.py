from everstaff.core.constants import (
    STALE_SESSION_THRESHOLD_SECONDS,
    TOOL_MAX_RESULTS,
    TOOL_MAX_LINE_WIDTH,
)

def test_constants_are_positive_ints():
    assert isinstance(STALE_SESSION_THRESHOLD_SECONDS, int) and STALE_SESSION_THRESHOLD_SECONDS > 0
    assert isinstance(TOOL_MAX_RESULTS, int) and TOOL_MAX_RESULTS > 0
    assert isinstance(TOOL_MAX_LINE_WIDTH, int) and TOOL_MAX_LINE_WIDTH > 0

def test_stale_threshold_is_300():
    assert STALE_SESSION_THRESHOLD_SECONDS == 300

def test_max_results_is_200():
    assert TOOL_MAX_RESULTS == 200

def test_max_line_width_is_2000():
    assert TOOL_MAX_LINE_WIDTH == 2000
