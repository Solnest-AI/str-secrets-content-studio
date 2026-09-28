#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# dependencies = ["playwright==1.60.0", "pillow>=10"]
# ///
"""Check what carousels need and fix what can be fixed without the host.

The host never runs a command. scripts/setup.py (the installer) runs this through uv, and
Claude can run it again if a carousel script fails to start:
  "$SKILL/bin/uv" run "$SKILL/scripts/doctor.py"

`uv run` installs the Python packages from the header above on first use. This script
then installs the headless browser if it is missing (about 200 MB, one time, no admin).
Videos are checked by setup.py (ffmpeg, the KIE key, the balance), not here.

Every line starts with [ok] or [failed]. Exit 0 = ready, 2 = something could not be
fixed (the line says what). Output is ASCII only so a Windows console can never crash on it.
"""
import argparse
import pathlib
import sys


def say(tag, msg):
    print(f"[{tag}] {msg}".encode("ascii", "replace").decode("ascii"), flush=True)


def check_carousel():
    ok = True
    say("ok", f"Python {sys.version.split()[0]}")
    try:
        import PIL
        say("ok", f"Pillow {PIL.__version__}")
    except ImportError:
        say("failed", "Pillow is missing: run this through uv (bin/uv run scripts/doctor.py), not plain python")
        return False
    try:
        import importlib.metadata as md
        from playwright.sync_api import sync_playwright
        say("ok", f"Playwright {md.version('playwright')}")
    except ImportError:
        say("failed", "Playwright is missing: run this through uv (bin/uv run scripts/doctor.py), not plain python")
        return False
    try:
        import browser
        with sync_playwright() as pw:
            b = browser.launch(pw)
            b.close()
        say("ok", "headless browser starts")
    except Exception as e:
        say("failed", f"headless browser: {str(e).splitlines()[0][:200]}")
        ok = False
    try:
        from carousel import FONT_DIR, FONTS
        missing = [f for spec in FONTS.values() for k in ("roman", "italic") if (f := spec.get(k))
                   and not (FONT_DIR / f).exists()]
        if missing:
            say("failed", f"fonts missing from {FONT_DIR}: {missing} (re-copy the skill folder)")
            ok = False
        else:
            say("ok", "bundled fonts")
    except Exception as e:
        say("failed", f"carousel builder would not load: {e}")
        ok = False
    return ok


def main(argv=None):
    argparse.ArgumentParser(description=__doc__,
                            formatter_class=argparse.RawDescriptionHelpFormatter).parse_args(argv)
    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
    if check_carousel():
        say("ok", "READY")
        return 0
    say("failed", "not ready (see the [failed] lines above)")
    return 2


if __name__ == "__main__":
    sys.exit(main())
