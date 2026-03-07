#!/usr/bin/env bash
# Lint: detect logging anti-patterns in Python source files.
# Checks:
#   1. Manual [XXX] prefixes in log messages
#   2. _logger variable name (should be logger)

set -euo pipefail

errors=0

# Check provided files, or all Python files under src/everstaff/
if [ $# -gt 0 ]; then
    files=("$@")
else
    files=()
    while IFS= read -r f; do
        files+=("$f")
    done < <(find src/everstaff -name '*.py' -not -path '*/builtin_skills/*')
fi

for f in "${files[@]}"; do
    [ -f "$f" ] || continue

    # Check 1: Manual [XXX] prefixes in log messages
    if grep -nE 'logger\.(info|debug|warning|error|exception)\(.*"\[' "$f" 2>/dev/null; then
        echo "ERROR: $f — log message contains manual [XXX] prefix (use __name__ instead)"
        errors=$((errors + 1))
    fi

    # Check 2: _logger variable name
    if grep -nE '(^|[^a-zA-Z0-9])_logger\s*=\s*logging\.getLogger' "$f" 2>/dev/null; then
        echo "ERROR: $f — use 'logger' not '_logger'"
        errors=$((errors + 1))
    fi
done

if [ "$errors" -gt 0 ]; then
    echo ""
    echo "Found $errors logging format violation(s). See docs/plans/2026-03-08-unified-logging-design.md for rules."
    exit 1
fi
