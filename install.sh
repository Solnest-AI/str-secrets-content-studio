#!/usr/bin/env bash
# STR Secrets Content Studio installer (macOS / Linux; on Windows Git Bash it hands off to
# install.ps1). No admin rights, no PATH edits, nothing to type afterwards. Re-run any
# time to update or repair; it keeps your .env and the downloaded ffmpeg.
#
# Run it from Claude Code's Bash tool, or any terminal:
#   bash -o pipefail -c "curl -fsSL https://raw.githubusercontent.com/Solnest-AI/str-secrets-content-studio/main/install.sh | bash"
#
# What it does: copies the skill into ~/.claude/skills/, finds a Python 3.9+ (or installs
# one through uv, the same way the STR Secrets Connections kit does), then hands over to
# scripts/setup.py for ffmpeg, the KIE key, the balance and the launcher.
set -u

REPO="Solnest-AI/str-secrets-content-studio"
BRANCH="${STUDIO_BRANCH:-main}"      # override to test a branch
NAME="str-secrets-content-studio"
DEST="$HOME/.claude/skills/$NAME"
HERE=""
if [ -n "${BASH_SOURCE[0]:-}" ] && [ -f "${BASH_SOURCE[0]}" ]; then
  HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
fi

OS="$(uname -s)"
case "$OS" in
  MINGW*|MSYS*|CYGWIN*)
    if [ -n "$HERE" ] && [ -f "$HERE/install.ps1" ]; then
      exec powershell.exe -NoProfile -ExecutionPolicy Bypass -File "$(cygpath -w "$HERE/install.ps1")"
    fi
    exec powershell.exe -NoProfile -ExecutionPolicy Bypass -Command "irm https://raw.githubusercontent.com/$REPO/$BRANCH/install.ps1 | iex"
    ;;
esac

echo "STR Secrets Content Studio installer ($OS)"

# 1. The skill files: a local clone if we are running from one, else the latest zip.
SRC=""
TMP=""
if [ -n "$HERE" ] && [ -f "$HERE/skill/$NAME/SKILL.md" ]; then
  SRC="$HERE/skill/$NAME"
else
  TMP="$(mktemp -d 2>/dev/null || mktemp -d -t content-studio)"
  echo "  downloading the skill..."
  if ! curl -fsSL --retry 3 "https://github.com/$REPO/archive/refs/heads/$BRANCH.zip" -o "$TMP/repo.zip"; then
    echo "ERROR: could not download the skill from GitHub. Check the internet connection and run this again."
    exit 2
  fi
  if command -v unzip >/dev/null 2>&1; then
    unzip -q "$TMP/repo.zip" -d "$TMP"
  else
    tar -xf "$TMP/repo.zip" -C "$TMP"
  fi
  SRC="$(ls -d "$TMP"/str-secrets-content-studio-*/skill/"$NAME" 2>/dev/null | head -1)"
  if [ -z "$SRC" ] || [ ! -f "$SRC/SKILL.md" ]; then
    echo "ERROR: the download did not contain the skill folder."
    exit 2
  fi
fi
mkdir -p "$DEST"
rm -rf "$DEST/scripts"
cp -R "$SRC/." "$DEST/"
echo "  skill installed at $DEST"

# 2. A Python that works here (3.9 or newer). On a Mac without the Xcode command line
#    tools, /usr/bin/python3 is a stub that pops up a dialog, so it is skipped.
python_ok() { "$1" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 9) else 1)' >/dev/null 2>&1; }
PY=""
for c in python3 python; do
  p="$(command -v "$c" 2>/dev/null)" || continue
  if [ "$OS" = "Darwin" ] && { [ "$p" = "/usr/bin/python3" ] || [ "$p" = "/usr/bin/python" ]; }; then
    xcode-select -p >/dev/null 2>&1 || continue
  fi
  python_ok "$p" && { PY="$p"; break; }
done
if [ -z "$PY" ]; then
  for u in uv "$HOME/.local/bin/uv"; do
    command -v "$u" >/dev/null 2>&1 || continue
    p="$("$u" python find 3.13 2>/dev/null)" && python_ok "$p" && { PY="$p"; break; }
    "$u" python install 3.13 >/dev/null 2>&1
    p="$("$u" python find 3.13 2>/dev/null)" && python_ok "$p" && { PY="$p"; break; }
  done
fi
if [ -z "$PY" ]; then
  echo "  installing Python (through uv, no admin needed)..."
  if ! curl -LsSf https://astral.sh/uv/install.sh | sh >/dev/null 2>&1; then
    echo "ERROR: could not install uv (https://astral.sh/uv). Check the internet connection and run this again."
    exit 2
  fi
  UV="$HOME/.local/bin/uv"
  "$UV" python install 3.13 >/dev/null 2>&1
  p="$("$UV" python find 3.13 2>/dev/null)" && python_ok "$p" && PY="$p"
fi
if [ -z "$PY" ]; then
  echo "ERROR: no working Python 3.9+ was found and the automatic install failed."
  exit 2
fi

# 3. Everything else (ffmpeg, the KIE key, the balance, the launcher) is setup.py's job.
"$PY" "$DEST/scripts/setup.py"
rc=$?
[ -n "$TMP" ] && rm -rf "$TMP"
exit $rc
