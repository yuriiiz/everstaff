#!/usr/bin/env bash
# =============================================================================
# Release helper — validates version consistency, optionally fixes, then tags.
#
# Usage:
#   ./scripts/release.sh              # check only (version from pyproject.toml)
#   ./scripts/release.sh 0.2.0        # check against specific version
#   ./scripts/release.sh --fix        # auto-fix all files to pyproject.toml version
#   ./scripts/release.sh --fix 0.2.0  # set everything to 0.2.0 and commit
# =============================================================================
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PYPROJECT="$ROOT/pyproject.toml"
SCAFFOLD="$ROOT/src/everstaff/scaffold.py"
DOCS_DIR="$ROOT/docs"

# ---------------------------------------------------------------------------
# Parse args
# ---------------------------------------------------------------------------
FIX=false
EXPECTED=""

for arg in "$@"; do
    if [[ "$arg" == "--fix" ]]; then
        FIX=true
    elif [[ -z "$EXPECTED" ]]; then
        EXPECTED="$arg"
    fi
done

PYPROJECT_VERSION=$(grep -m1 '^version' "$PYPROJECT" | sed 's/.*"\(.*\)".*/\1/')
EXPECTED="${EXPECTED:-$PYPROJECT_VERSION}"
TAG="v${EXPECTED}"
ERRORS=()
FIXED=()

echo "Release check for version: $EXPECTED (tag: $TAG)"
echo "---------------------------------------------------"

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
check_or_fix_sed() {
    # $1 = label, $2 = file, $3 = sed pattern, $4 = description
    local label="$1" file="$2" pattern="$3" desc="$4"
    if $FIX; then
        sed -i '' "$pattern" "$file"
        FIXED+=("$label: $desc")
    else
        ERRORS+=("$label: $desc")
    fi
}

# ---------------------------------------------------------------------------
# 1. pyproject.toml version
# ---------------------------------------------------------------------------
if [[ "$PYPROJECT_VERSION" != "$EXPECTED" ]]; then
    if $FIX; then
        sed -i '' "s/^version = \".*\"/version = \"$EXPECTED\"/" "$PYPROJECT"
        FIXED+=("pyproject.toml: version \"$PYPROJECT_VERSION\" -> \"$EXPECTED\"")
    else
        ERRORS+=("pyproject.toml: version is \"$PYPROJECT_VERSION\", expected \"$EXPECTED\"")
    fi
else
    echo "[OK] pyproject.toml version = $PYPROJECT_VERSION"
fi

# ---------------------------------------------------------------------------
# 2. scaffold.py dependency pin
# ---------------------------------------------------------------------------
SCAFFOLD_VERSION=$(sed -n 's/.*everstaff>=\([0-9][0-9.a-zA-Z]*\).*/\1/p' "$SCAFFOLD" | head -1)
SCAFFOLD_VERSION="${SCAFFOLD_VERSION:-NOT_FOUND}"
if [[ "$SCAFFOLD_VERSION" != "$EXPECTED" ]]; then
    check_or_fix_sed "scaffold.py" "$SCAFFOLD" \
        "s/everstaff>=[0-9][0-9.a-zA-Z]*/everstaff>=$EXPECTED/" \
        "everstaff>=$SCAFFOLD_VERSION -> everstaff>=$EXPECTED"
else
    echo "[OK] scaffold.py dependency = everstaff>=$SCAFFOLD_VERSION"
fi

# ---------------------------------------------------------------------------
# 3. docs — everstaff-x.y.z wheel references
# ---------------------------------------------------------------------------
if [[ -d "$DOCS_DIR" ]]; then
    STALE_FILES=$(grep -rl "everstaff-[0-9]" "$DOCS_DIR" --include='*.md' | grep -v "everstaff-${EXPECTED}" "$DOCS_DIR"/*.md 2>/dev/null | cut -d: -f1 | sort -u || true)
    # More reliable: find files that have old versions
    STALE_FILES=$(grep -rl "everstaff-[0-9]" "$DOCS_DIR" --include='*.md' 2>/dev/null || true)
    HAS_STALE=false
    for f in $STALE_FILES; do
        if grep -q "everstaff-[0-9]" "$f" && ! grep -q "everstaff-${EXPECTED}" "$f" || grep "everstaff-[0-9]" "$f" | grep -qv "everstaff-${EXPECTED}"; then
            HAS_STALE=true
            if $FIX; then
                sed -i '' "s/everstaff-[0-9][0-9.a-zA-Z]*/everstaff-$EXPECTED/g" "$f"
                FIXED+=("$(basename "$f"): updated wheel version references -> $EXPECTED")
            else
                ERRORS+=("$(basename "$f"): contains stale everstaff-*.whl references")
            fi
        fi
    done
    if ! $HAS_STALE; then
        echo "[OK] docs wheel references"
    fi

    # docs — "version": "x.y.z" in API examples
    STALE_API_FILES=$(grep -rln '"version":' "$DOCS_DIR" --include='*.md' 2>/dev/null || true)
    HAS_STALE_API=false
    for f in $STALE_API_FILES; do
        if grep '"version":' "$f" | grep -qv "\"$EXPECTED\""; then
            HAS_STALE_API=true
            if $FIX; then
                sed -i '' "s/\"version\": \"[0-9][0-9.a-zA-Z]*\"/\"version\": \"$EXPECTED\"/" "$f"
                FIXED+=("$(basename "$f"): updated API version -> $EXPECTED")
            else
                ERRORS+=("$(basename "$f"): contains stale API version string")
            fi
        fi
    done
    if ! $HAS_STALE_API; then
        echo "[OK] docs API version"
    fi
fi

# ---------------------------------------------------------------------------
# 4. If we fixed things, show what changed and offer to commit
# ---------------------------------------------------------------------------
if [[ ${#FIXED[@]} -gt 0 ]]; then
    echo ""
    echo "Fixed ${#FIXED[@]} item(s):"
    for f in "${FIXED[@]}"; do
        echo "  [FIXED] $f"
    done
    echo ""
    read -rp "Commit version bump? [y/N] " COMMIT
    if [[ "$COMMIT" =~ ^[Yy]$ ]]; then
        git -C "$ROOT" add -A
        git -C "$ROOT" commit -m "chore: bump version to $EXPECTED"
        echo "Committed."
    else
        echo "Files updated but not committed. Review with: git diff"
    fi
    # Re-read pyproject version after fix
    PYPROJECT_VERSION="$EXPECTED"
fi

# ---------------------------------------------------------------------------
# 5. Check tag doesn't already exist
# ---------------------------------------------------------------------------
if git -C "$ROOT" rev-parse "$TAG" >/dev/null 2>&1; then
    ERRORS+=("git tag $TAG already exists")
else
    echo "[OK] tag $TAG is available"
fi

# ---------------------------------------------------------------------------
# 6. Check working tree is clean (skip if we just committed via --fix)
# ---------------------------------------------------------------------------
if ! git -C "$ROOT" diff --quiet HEAD 2>/dev/null; then
    if $FIX && [[ ${#FIXED[@]} -gt 0 ]]; then
        ERRORS+=("working tree still has uncommitted changes after fix")
    else
        ERRORS+=("working tree has uncommitted changes — commit first, or use --fix")
    fi
else
    echo "[OK] working tree is clean"
fi

# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------
echo "---------------------------------------------------"

if [[ ${#ERRORS[@]} -gt 0 ]]; then
    echo "FAILED — ${#ERRORS[@]} issue(s) found:"
    for err in "${ERRORS[@]}"; do
        echo "  - $err"
    done
    if ! $FIX; then
        echo ""
        echo "Tip: run with --fix to auto-repair version references:"
        echo "  ./scripts/release.sh --fix $EXPECTED"
    fi
    exit 1
fi

# ---------------------------------------------------------------------------
# 7. Create tag
# ---------------------------------------------------------------------------
echo "All checks passed."
read -rp "Create and push tag $TAG? [y/N] " CONFIRM
if [[ "$CONFIRM" =~ ^[Yy]$ ]]; then
    git -C "$ROOT" tag -a "$TAG" -m "Release $EXPECTED"
    git -C "$ROOT" push origin "$TAG"
    echo "Done! Tag $TAG pushed."
else
    echo "Aborted. You can create the tag manually:"
    echo "  git tag -a $TAG -m \"Release $EXPECTED\""
    echo "  git push origin $TAG"
fi
