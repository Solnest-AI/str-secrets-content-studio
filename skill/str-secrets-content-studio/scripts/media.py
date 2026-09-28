#!/usr/bin/env python3
"""Shared ffmpeg helpers for the STR Secrets Content Studio. Python stdlib only.
Output is ASCII only so a Windows console can never crash on it.

ffmpeg and ffprobe are looked up in this order:
  1. this skill's own bin/ folder (scripts/setup.py downloads them there; no admin,
     no PATH edits, no terminal restart)
  2. PATH
  3. the usual install spots that the Claude Code app's PATH tends to miss
     (Homebrew, winget, chocolatey, scoop)
"""
import json
import os
import pathlib
import shutil
import subprocess
import sys

ASPECTS = {"9:16": (1080, 1920), "16:9": (1920, 1080), "1:1": (1080, 1080)}

# When stdout is a pipe (it always is under Claude Code) Windows Python falls back to the
# locale code page, and printing a path with a non-Latin user name would then crash.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

SKILL_DIR = pathlib.Path(__file__).resolve().parent.parent
BIN_DIR = SKILL_DIR / "bin"
EXE = ".exe" if os.name == "nt" else ""

INSTALL_HINT = ("Run the setup once; it downloads ffmpeg into this skill's bin folder:\n"
                f"  <python> \"{SKILL_DIR / 'scripts' / 'setup.py'}\"\n"
                "Manual fallback: macOS brew install ffmpeg, Windows winget install --id "
                "Gyan.FFmpeg -e, Linux sudo apt install ffmpeg, then restart Claude Code.")


class MediaError(RuntimeError):
    pass


def candidates(name):
    """Every place a ffmpeg/ffprobe binary might live, most trusted first."""
    yield BIN_DIR / f"{name}{EXE}"
    found = shutil.which(name)
    if found:
        yield pathlib.Path(found)
    home = pathlib.Path.home()
    if os.name == "nt":
        local = pathlib.Path(os.environ.get("LOCALAPPDATA") or home / "AppData" / "Local")
        yield local / "Microsoft" / "WinGet" / "Links" / f"{name}.exe"
        try:
            yield from sorted((local / "Microsoft" / "WinGet" / "Packages")
                              .glob(f"Gyan.FFmpeg*/*/bin/{name}.exe"))
        except OSError:
            pass
        yield (pathlib.Path(os.environ.get("ProgramData") or "C:/ProgramData")
               / "chocolatey" / "bin" / f"{name}.exe")
        yield home / "scoop" / "shims" / f"{name}.exe"
        yield pathlib.Path("C:/ffmpeg/bin") / f"{name}.exe"
        yield home / ".local" / "bin" / f"{name}.exe"   # where the summit prep puts it
    else:
        for d in ("/opt/homebrew/bin", "/usr/local/bin", "/opt/local/bin", "/usr/bin",
                  "/snap/bin"):
            yield pathlib.Path(d) / name
        yield home / ".local" / "bin" / name


_CACHE = {}


def tool(name):
    """Absolute path of ffmpeg or ffprobe, or a MediaError that says how to fix it."""
    if name not in _CACHE:
        for c in candidates(name):
            try:
                if c.is_file() and os.access(c, os.X_OK):
                    _CACHE[name] = str(c)
                    break
            except OSError:
                continue
        else:
            raise MediaError(f"{name} not found. {INSTALL_HINT}")
    return _CACHE[name]


def version(path):
    """First line of `<tool> -version`, or '' if it does not run here."""
    try:
        r = subprocess.run([str(path), "-version"], capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=30)
    except (OSError, subprocess.SubprocessError):
        return ""
    line = (r.stdout or "").splitlines()[0] if r.stdout else ""
    return line if r.returncode == 0 and "version" in line else ""


def run(cmd):
    r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if r.returncode != 0:
        tail = "\n".join((r.stderr or "").strip().splitlines()[-12:])
        raise MediaError(f"{cmd[0]} failed:\n{tail}")
    return r


def probe(path):
    """Return {'w','h','secs'} for an image or video."""
    r = run([tool("ffprobe"), "-v", "error", "-select_streams", "v:0",
             "-show_entries", "stream=width,height", "-show_entries", "format=duration",
             "-of", "json", str(path)])
    d = json.loads(r.stdout)
    if not d.get("streams"):
        raise MediaError(f"no picture stream in {path}")
    s = d["streams"][0]
    secs = d.get("format", {}).get("duration")
    return {"w": int(s["width"]), "h": int(s["height"]),
            "secs": float(secs) if secs not in (None, "N/A") else 0.0}


def last_frame(video, out_jpg):
    """Extract the true final frame of a clip (used to seed the closing shot)."""
    run([tool("ffmpeg"), "-y", "-v", "error", "-sseof", "-0.1", "-i", str(video),
         "-frames:v", "1", "-q:v", "2", str(out_jpg)])
    return out_jpg


if __name__ == "__main__":
    try:
        for name in ("ffmpeg", "ffprobe"):
            p = tool(name)
            print(f"{name:<8} {p}")
            print(f"         {version(p) or 'DOES NOT RUN on this machine'}")
    except MediaError as e:
        print(f"ERROR: {e}")
        sys.exit(1)
