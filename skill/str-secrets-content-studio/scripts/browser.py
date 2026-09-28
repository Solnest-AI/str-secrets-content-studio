"""Start headless Chromium for the carousel scripts, installing it first on a machine that
has never had it. The host never types `playwright install`: the first run does it (about
200 MB, once, into the user's own cache, no admin rights needed), then launches again.
`--only-shell` fetches just the headless build: 193 MB instead of 534 MB for the full
install (measured 2026-09-26). Headless launches use it; nothing here opens a window."""
import subprocess
import sys

_MISSING = ("Executable doesn't exist", "playwright install", "Looks like Playwright")


def launch(pw):
    try:
        return pw.chromium.launch()
    except Exception as e:  # Playwright raises its own Error type; match on the message
        if not any(m in str(e) for m in _MISSING):
            raise
    print("First run: installing the headless browser (about 200 MB, one time)...", flush=True)
    r = subprocess.run([sys.executable, "-m", "playwright", "install", "chromium", "--only-shell"],
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    if r.returncode != 0:
        tail = "\n".join((r.stderr or r.stdout or "").strip().splitlines()[-8:])
        raise RuntimeError(f"could not install the headless browser:\n{tail}")
    return pw.chromium.launch()
