"""Framework-wide fixed constants. Not user-configurable."""

# Session management
STALE_SESSION_THRESHOLD_SECONDS = 300   # mark as interrupted if running > 5 min with no update

# Tool output limits (non-configurable hard caps)
TOOL_MAX_RESULTS = 200        # max grep/glob results
TOOL_MAX_LINE_WIDTH = 2000    # max chars per line in file reader
