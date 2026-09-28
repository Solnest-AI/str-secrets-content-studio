#!/usr/bin/env python3
"""One-shot setup and health check for the STR Secrets Content Studio. Stdlib only.

Checks, and fixes without asking, everything the skill needs on THIS computer:
  * ffmpeg + ffprobe: reused if the machine has them, else downloaded into <skill>/bin/
    (no admin rights, no PATH edits, no terminal restart; several mirrors are tried)
  * a Python launcher at <skill>/bin/py (and bin/py.cmd for Windows PowerShell) so every
    later command runs the same on Mac and Windows whatever Python is called here
  * the KIE key: reused from the STR Secrets Connections kit if it is on this machine,
    else a blank .env is created and opened for the attendee to paste into. The key is
    never printed and never asked for in chat.
  * the KIE balance (455 credits is one 30 second video)
  * an earlier copy of this same skill under another folder name (found by its files, not
    its name): its KIE key is carried over, then the copy is moved out of ~/.claude/skills
    into ~/.claude/skills-retired, so Claude has one content skill, not two that answer the
    same request. Nothing is deleted; setup prints the one move that undoes it.
    STUDIO_KEEP_COPIES=1 leaves such a copy where it is.

Usage:
  <python> setup.py             check everything and fix what it can
  <python> setup.py --offline   no network: skip downloads and the balance check
  <python> setup.py --no-open   do not open .env in an editor when the key is missing

Exit codes: 0 ready (a low balance is a warning), 1 the attendee must add the KIE key,
2 hard failure (ffmpeg could not be downloaded, Python too old).
"""
import argparse
import gzip
import os
import pathlib
import platform
import shutil
import subprocess
import sys
import tarfile
import time
import urllib.error
import urllib.request
import zipfile

import kie
import media
from media import BIN_DIR, SKILL_DIR

NEEDED = ("ffmpeg", "ffprobe")
VIDEO_CREDITS = 455          # 6 beats + closing shot
MIN_PYTHON = (3, 9)

GH = "https://github.com/eugeneware/ffmpeg-static/releases/download/b6.1.1"
BTBN = "https://github.com/BtbN/FFmpeg-Builds/releases/download/latest"
MR = "https://ffmpeg.martin-riedl.de/redirect/latest/macos/{arch}/release"


def _pair(tag):
    return [{"url": f"{GH}/ffmpeg-{tag}.gz", "gz": "ffmpeg"},
            {"url": f"{GH}/ffprobe-{tag}.gz", "gz": "ffprobe"}]


# Each source is (label, parts). A part is a URL of an archive holding ffmpeg and/or
# ffprobe, or a single gzipped binary named by "gz". Tried in order until one runs.
SOURCES = {
    ("Windows", "x64"): [
        ("gyan.dev", [{"url": "https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip"}]),
        ("BtbN on GitHub", [{"url": f"{BTBN}/ffmpeg-master-latest-win64-gpl.zip"}]),
        ("ffmpeg-static on GitHub", _pair("win32-x64")),
    ],
    ("Darwin", "arm64"): [
        ("ffmpeg-static on GitHub", _pair("darwin-arm64")),
        ("martin-riedl.de", [{"url": MR.format(arch="arm64") + "/ffmpeg.zip"},
                             {"url": MR.format(arch="arm64") + "/ffprobe.zip"}]),
    ],
    ("Darwin", "x64"): [
        ("ffmpeg-static on GitHub", _pair("darwin-x64")),
        ("martin-riedl.de", [{"url": MR.format(arch="amd64") + "/ffmpeg.zip"},
                             {"url": MR.format(arch="amd64") + "/ffprobe.zip"}]),
        ("evermeet.cx", [{"url": "https://evermeet.cx/ffmpeg/getrelease/zip"},
                         {"url": "https://evermeet.cx/ffmpeg/getrelease/ffprobe/zip"}]),
    ],
    ("Linux", "x64"): [
        ("BtbN on GitHub", [{"url": f"{BTBN}/ffmpeg-master-latest-linux64-gpl.tar.xz"}]),
        ("ffmpeg-static on GitHub", _pair("linux-x64")),
    ],
    ("Linux", "arm64"): [
        ("BtbN on GitHub", [{"url": f"{BTBN}/ffmpeg-master-latest-linuxarm64-gpl.tar.xz"}]),
        ("ffmpeg-static on GitHub", _pair("linux-arm64")),
    ],
}
SOURCES[("Windows", "arm64")] = SOURCES[("Windows", "x64")]     # runs under emulation


def platform_key():
    m = platform.machine().lower()
    return platform.system(), ("arm64" if m in ("arm64", "aarch64") else "x64")


def sources_for(system, arch):
    return SOURCES.get((system, arch), [])


# ---------------------------------------------------------------- ffmpeg

def download(url, dest, timeout=60):
    """Stream url to dest, printing an ASCII dot every 4 MB. Returns bytes written."""
    req = urllib.request.Request(url, headers={"User-Agent": kie.UA})
    part = dest.with_name(dest.name + ".part")
    got, next_dot = 0, 4 * 1024 * 1024
    with urllib.request.urlopen(req, timeout=timeout) as r, open(part, "wb") as f:
        while True:
            chunk = r.read(1024 * 1024)
            if not chunk:
                break
            f.write(chunk)
            got += len(chunk)
            if got >= next_dot:
                print(".", end="", flush=True)
                next_dot += 4 * 1024 * 1024
    part.replace(dest)
    return got


def harvest(archive, into, gz_name=None):
    """Pull the ffmpeg/ffprobe binaries out of a zip, a tar(.xz/.gz), or a single
    gzipped binary, into `into`. Returns the tool names found."""
    archive, into = pathlib.Path(archive), pathlib.Path(into)
    into.mkdir(parents=True, exist_ok=True)
    wanted = {n + media.EXE: n for n in NEEDED}
    found = []
    if gz_name:
        with gzip.open(archive, "rb") as src, open(into / (gz_name + media.EXE), "wb") as dst:
            shutil.copyfileobj(src, dst)
        return [gz_name]
    if zipfile.is_zipfile(archive):
        with zipfile.ZipFile(archive) as z:
            for info in z.infolist():
                base = pathlib.PurePosixPath(info.filename).name
                if base in wanted and not info.is_dir():
                    with z.open(info) as src, open(into / base, "wb") as dst:
                        shutil.copyfileobj(src, dst)
                    found.append(wanted[base])
        return found
    if tarfile.is_tarfile(archive):
        with tarfile.open(archive) as t:
            for m in t.getmembers():
                base = pathlib.PurePosixPath(m.name).name
                if base in wanted and m.isfile():
                    src = t.extractfile(m)
                    with open(into / base, "wb") as dst:
                        shutil.copyfileobj(src, dst)
                    found.append(wanted[base])
        return found
    raise media.MediaError(f"{archive.name} is not a zip, tar or gz file")


def make_executable(path):
    try:
        os.chmod(path, 0o755)
    except OSError:
        pass
    if sys.platform == "darwin":       # not set by urllib, but be sure Gatekeeper stays quiet
        subprocess.run(["xattr", "-d", "com.apple.quarantine", str(path)],
                       capture_output=True)


def ensure_ffmpeg(offline=False):
    """Return ({name: (path, version line)}, error_or_None). Downloads into bin/ if the
    machine has no working copy."""
    have = {}
    for n in NEEDED:
        try:
            p = media.tool(n)
            v = media.version(p)
            if v:
                have[n] = (p, v)
        except media.MediaError:
            pass
    if len(have) == len(NEEDED):
        return have, None
    if offline:
        return have, "offline, not downloading"
    system, arch = platform_key()
    srcs = sources_for(system, arch)
    if not srcs:
        return have, f"no download source for {system}/{arch}; install ffmpeg by hand"
    errors = []
    dl = BIN_DIR / "_download"
    for label, parts in srcs:
        print(f"  downloading ffmpeg from {label} ", end="", flush=True)
        try:
            dl.mkdir(parents=True, exist_ok=True)
            for part in parts:
                name = part["url"].rsplit("/", 1)[-1].split("?")[0] or "download.bin"
                path = dl / name
                download(part["url"], path)
                harvest(path, BIN_DIR, gz_name=part.get("gz"))
            media._CACHE.clear()
            got = {}
            for n in NEEDED:
                p = BIN_DIR / (n + media.EXE)
                if not p.is_file():
                    raise media.MediaError(f"{label} did not contain {n}")
                make_executable(p)
                v = media.version(p)
                if not v:
                    raise media.MediaError(f"{n} from {label} does not run on this machine")
                got[n] = (str(p), v)
            print(" ok", flush=True)
            shutil.rmtree(dl, ignore_errors=True)
            return got, None
        except (urllib.error.URLError, TimeoutError, OSError, media.MediaError,
                zipfile.BadZipFile, tarfile.TarError, EOFError) as e:
            print(" failed", flush=True)
            errors.append(f"{label}: {str(e)[:140]}")
            for n in NEEDED:
                try:
                    (BIN_DIR / (n + media.EXE)).unlink()
                except OSError:
                    pass
    shutil.rmtree(dl, ignore_errors=True)
    media._CACHE.clear()
    return have, "every download failed: " + " | ".join(errors)


# ---------------------------------------------------------------- launcher

SH_LAUNCHER = """#!/bin/sh
# Python launcher for the STR Secrets Content Studio, written by scripts/setup.py.
# Runs the Python found at setup time; falls back to whatever works if it moved.
P="{py}"
if [ -x "$P" ]; then exec "$P" "$@"; fi
for c in python3 python; do
  q="$(command -v "$c" 2>/dev/null)" || continue
  case "$q" in
    *WindowsApps*) continue ;;
    /usr/bin/python3) xcode-select -p >/dev/null 2>&1 || continue ;;
  esac
  "$q" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 9) else 1)' >/dev/null 2>&1 && exec "$q" "$@"
done
for u in uv "$HOME/.local/bin/uv"; do
  command -v "$u" >/dev/null 2>&1 && exec "$u" run --no-project --python 3.13 python "$@"
done
echo "ERROR: no Python found. Re-run the installer from INSTALL.md" >&2
exit 1
"""

CMD_LAUNCHER = """@echo off
rem Python launcher for the STR Secrets Content Studio (PowerShell / cmd), written by scripts\\setup.py.
rem Runs the Python found at setup time; falls back to whatever works if it moved.
set "P={py}"
if exist "%P%" goto run
where uv >nul 2>&1 && goto uv
if exist "%USERPROFILE%\\.local\\bin\\uv.exe" goto uvhome
py -3 -c "import sys" >nul 2>&1 && goto runpy
echo ERROR: no Python found. Re-run the installer from INSTALL.md 1>&2
exit /b 1
:run
"%P%" %*
exit /b %errorlevel%
:uv
uv run --no-project --python 3.13 python %*
exit /b %errorlevel%
:uvhome
"%USERPROFILE%\\.local\\bin\\uv.exe" run --no-project --python 3.13 python %*
exit /b %errorlevel%
:runpy
py -3 %*
exit /b %errorlevel%
"""


def python_for_launcher():
    """The interpreter running this script, except the Windows Store alias is kept as
    the alias (its real path under Program Files\\WindowsApps is not always runnable)."""
    exe = pathlib.Path(sys.executable)
    try:
        real = exe.resolve()
    except OSError:
        real = exe
    if os.name == "nt" and "windowsapps" in str(real).lower():
        alias = (pathlib.Path(os.environ.get("LOCALAPPDATA", "")) / "Microsoft" / "WindowsApps"
                 / "python3.exe")
        return alias if alias.exists() else exe
    return real


def write_launchers():
    """Write bin/py (sh, for Mac and Git Bash) and bin/py.cmd (Windows). Returns paths."""
    BIN_DIR.mkdir(parents=True, exist_ok=True)
    py = python_for_launcher()
    sh = BIN_DIR / "py"
    with open(sh, "w", encoding="utf-8", newline="\n") as f:      # LF, or sh chokes on \r
        f.write(SH_LAUNCHER.replace("{py}", py.as_posix()))
    make_executable(sh)
    cmd = BIN_DIR / "py.cmd"
    with open(cmd, "w", encoding="utf-8", newline="\r\n") as f:
        f.write(CMD_LAUNCHER.replace("{py}", str(py)))
    return sh, cmd


# ---------------------------------------------------------------- carousels

SCRIPTS_DIR = pathlib.Path(__file__).resolve().parent

UV_SH = """#!/bin/sh
# uv launcher for the Content Studio carousel scripts, written by scripts/setup.py.
# Windows (Git Bash): uv's default Python home is under AppData, which the Claude desktop app
# (a Microsoft Store app) silently redirects, and `uv python install` fails there. Keep
# Python under the profile, as the STR Secrets connections kit does.
if [ -n "${USERPROFILE:-}" ] && [ -z "${UV_PYTHON_INSTALL_DIR:-}" ]; then
  export UV_PYTHON_INSTALL_DIR="$USERPROFILE\\.uv\\python"
fi
U="{uv}"
if [ -x "$U" ]; then exec "$U" "$@"; fi
for u in uv "$HOME/.local/bin/uv"; do
  command -v "$u" >/dev/null 2>&1 && exec "$u" "$@"
done
echo "ERROR: uv not found. Re-run the installer." >&2
exit 1
"""

UV_CMD = """@echo off
rem uv launcher for the Content Studio carousel scripts (PowerShell / cmd), written by scripts\\setup.py.
if not defined UV_PYTHON_INSTALL_DIR set "UV_PYTHON_INSTALL_DIR=%USERPROFILE%\\.uv\\python"
set "U={uv}"
if exist "%U%" goto run
where uv >nul 2>&1 && goto onpath
if exist "%USERPROFILE%\\.local\\bin\\uv.exe" goto home
echo ERROR: uv not found. Re-run the installer. 1>&2
exit /b 1
:run
"%U%" %*
exit /b %errorlevel%
:onpath
uv %*
exit /b %errorlevel%
:home
"%USERPROFILE%\\.local\\bin\\uv.exe" %*
exit /b %errorlevel%
"""


def find_uv():
    exe = "uv.exe" if os.name == "nt" else "uv"
    found = shutil.which("uv")
    for c in ([pathlib.Path(found)] if found else []) + [pathlib.Path.home() / ".local" / "bin" / exe,
                                                         pathlib.Path.home() / ".cargo" / "bin" / exe]:
        if c.exists():
            return c
    return None


def install_uv():
    """uv's official per-user installer (no admin), the same one the STR Secrets
    Connections kit uses. A fresh install is not on PATH yet, so it is found by path."""
    if os.name == "nt":
        cmd = ["powershell", "-NoProfile", "-ExecutionPolicy", "ByPass", "-c",
               "irm https://astral.sh/uv/install.ps1 | iex"]
    else:
        cmd = ["sh", "-c", "curl -LsSf https://astral.sh/uv/install.sh | sh"]
    try:
        subprocess.run(cmd, capture_output=True, text=True, timeout=300)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return find_uv()


def write_uv_launchers(uv):
    """bin/uv (sh, for Mac and Git Bash) and bin/uv.cmd (Windows): the carousel commands
    in CAROUSEL.md call these, so they work before uv is on PATH."""
    BIN_DIR.mkdir(parents=True, exist_ok=True)
    sh = BIN_DIR / "uv"
    with open(sh, "w", encoding="utf-8", newline="\n") as f:
        f.write(UV_SH.replace("{uv}", pathlib.Path(uv).as_posix()))
    make_executable(sh)
    with open(BIN_DIR / "uv.cmd", "w", encoding="utf-8", newline="\r\n") as f:
        f.write(UV_CMD.replace("{uv}", str(uv)))
    return sh


def ensure_carousel(offline=False):
    """Carousels need Pillow, Playwright and a headless browser, which uv installs from the
    scripts' own headers. doctor.py does the work (about 200 MB the first time). A failure
    here never blocks videos. Returns (ok, text)."""
    uv = find_uv() or (None if offline else install_uv())
    if not uv:
        return False, "uv could not be installed (carousels only). Run this setup again."
    write_uv_launchers(uv)
    if offline:
        return True, f"uv {pathlib.Path(uv).as_posix()} (browser check skipped: offline)"
    try:
        env = dict(os.environ)
        if os.name == "nt":   # see UV_SH: keep uv's Python out of the redirected AppData
            env.setdefault("UV_PYTHON_INSTALL_DIR", str(pathlib.Path.home() / ".uv" / "python"))
        r = subprocess.run([str(uv), "run", str(SCRIPTS_DIR / "doctor.py")], capture_output=True,
                           text=True, encoding="utf-8", errors="replace", timeout=1200, env=env)
    except (OSError, subprocess.TimeoutExpired) as e:
        return False, f"carousel setup did not finish ({e.__class__.__name__}). Run this setup again."
    if r.returncode == 0:
        return True, "packages, headless browser and fonts ready"
    out = (r.stdout or "") + "\n" + (r.stderr or "")
    fails = [l[len("[failed] "):] for l in out.splitlines() if l.startswith("[failed]")]
    last = fails[0] if fails else (out.strip().splitlines() or ["unknown error"])[-1]
    return False, last[:200] + " (run this setup again)"


# ---------------------------------------------------------------- KIE key

ENV_HEADER = ("# STR Secrets Content Studio. Paste your KIE key after the equals sign, save, done.\n"
              "# Get one at https://kie.ai/api-key (pay as you go, $5 minimum, about $2 per video).\n")


def write_env(path, value):
    """Set KIE_API_KEY=value in path, keeping every other line. Never prints the value."""
    path = pathlib.Path(path)
    lines = path.read_text(encoding="utf-8").splitlines() if path.exists() else ENV_HEADER.splitlines()
    done = False
    for i, line in enumerate(lines):
        if line.split("=", 1)[0].strip() == "KIE_API_KEY":
            lines[i] = f"KIE_API_KEY={value}"
            done = True
            break
    if not done:
        lines.append(f"KIE_API_KEY={value}")
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(lines) + "\n")
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass


def open_for_editing(path):
    try:
        if os.name == "nt":
            subprocess.Popen(["notepad.exe", str(path)])
        elif sys.platform == "darwin":
            subprocess.Popen(["open", "-e", str(path)])
        else:
            subprocess.Popen(["xdg-open", str(path)])
        return True
    except OSError:
        return False


def ensure_key(open_editor=True):
    """Return (True, where) when a key is in place, else (False, what to do)."""
    env_file = SKILL_DIR / ".env"
    try:
        key, where = kie.find_key()
    except kie.KieError:
        key, where = None, None
    if key:
        mine = kie._read_env_file(env_file).get("KIE_API_KEY", "")
        if mine == key:
            return True, f"in {env_file}"
        write_env(env_file, key)
        return True, f"found in {where}, copied into {env_file}"
    if kie._read_env_file(env_file).get("KIE_API_KEY", "") == "":
        write_env(env_file, "")
    opened = open_editor and open_for_editing(env_file)
    return False, (f"not found. Paste it into {'the file that just opened' if opened else 'this file'}"
                   f" after KIE_API_KEY= and save: {env_file}   (get one at https://kie.ai/api-key)")


# The files that make a folder a copy of this skill, whatever it is called: the same scripts
# ship in every earlier build of it. Another skill never carries all of them.
COPY_FINGERPRINT = ("SKILL.md", "CAROUSEL.md", "scripts/make_clips.py", "scripts/assemble.py",
                    "scripts/carousel.py", "scripts/listing_pull.py", "scripts/kie.py")


def earlier_copies(skills_root):
    """Folders in skills_root holding this skill under another name, never this one."""
    out = []
    try:
        entries = sorted(pathlib.Path(skills_root).iterdir())
    except OSError:
        return out
    for d in entries:
        if d.name == SKILL_DIR.name:
            continue
        try:
            if d.is_dir() and all((d / f).is_file() for f in COPY_FINGERPRINT):
                if not (SKILL_DIR.exists() and d.resolve() == SKILL_DIR.resolve()):
                    out.append(d)
        except OSError:
            continue
    return out


def retire_earlier_copies(skills_root=None, env_file=None, stamp=None):
    """Move earlier copies of this skill out of Claude's skills folder.

    Two copies make the same listing videos and carousels and answer the same requests, so
    with both installed Claude could pick either (2026-09-28: the summit guide linked an
    earlier build for a day before this skill had its own repo). Returns one dict per copy:
    from, moved_to (Path or None), key_carried, was_link, error.

    A copy's KIE key is copied first, only when this skill has none. A symlinked copy (a
    developer's checkout) is moved as the link itself: the checkout is never touched.
    Nothing is deleted."""
    root = pathlib.Path(skills_root) if skills_root else pathlib.Path.home() / ".claude" / "skills"
    env_file = pathlib.Path(env_file) if env_file else SKILL_DIR / ".env"
    results = []
    for old in earlier_copies(root):
        result = {"from": old, "moved_to": None, "key_carried": False, "was_link": old.is_symlink(),
                  "error": None}
        key = kie._read_env_file(old / ".env").get("KIE_API_KEY", "")
        if key and not kie._read_env_file(env_file).get("KIE_API_KEY", ""):
            write_env(env_file, key)
            result["key_carried"] = True
        if os.environ.get("STUDIO_KEEP_COPIES"):
            result["error"] = "left in place (STUDIO_KEEP_COPIES is set)"
        else:
            dest = root.parent / "skills-retired" / f"{old.name}-{stamp or time.strftime('%Y%m%d-%H%M%S')}"
            try:
                dest.parent.mkdir(parents=True, exist_ok=True)
                os.rename(old, dest)          # renames a symlink itself, never its target
                result["moved_to"] = dest
            except OSError as e:
                result["error"] = f"could not move it ({e.strerror or e})"
        results.append(result)
    return results


def check_balance():
    try:
        return kie.credits(), None
    except kie.KieError as e:
        return None, str(e)


# ---------------------------------------------------------------- main

def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--offline", action="store_true",
                    help="skip downloads and the balance check")
    ap.add_argument("--no-open", action="store_true",
                    help="do not open .env in an editor when the key is missing")
    a = ap.parse_args(argv)

    system, arch = platform_key()
    print(f"STR Secrets Content Studio setup ({system} {arch}, Python {platform.python_version()})")
    rows, problems, low_balance = [], set(), False

    def row(ok, label, text):
        rows.append(f"  [{'ok' if ok else '!!'}]  {label:<9} {text}")

    if sys.version_info < MIN_PYTHON:
        row(False, "Python", f"{platform.python_version()} is too old, need 3.9 or newer")
        problems.add("python")
    else:
        row(True, "Python", python_for_launcher().as_posix())

    have, err = ensure_ffmpeg(a.offline)
    for n in NEEDED:
        if n in have:
            row(True, n, f"{have[n][1].split(' Copyright')[0]}   {have[n][0]}")
        else:
            row(False, n, err or "missing")
            problems.add("ffmpeg")

    sh, cmd = write_launchers()
    row(True, "launcher", f"{sh.as_posix()}  (Windows PowerShell: {cmd.name})")

    for old in retire_earlier_copies():
        name = old["from"].name
        if old["moved_to"]:
            row(True, "old copy", f"an earlier copy of this skill ({name}) moved to "
                                  f"{old['moved_to'].as_posix()} so Claude uses one content skill"
                                  + (" (its KIE key was carried over)" if old["key_carried"] else "")
                                  + f". To undo, move that folder back to {old['from'].as_posix()}")
        else:
            row(False, "old copy", f"an earlier copy of this skill ({name}) is also installed and was "
                                   f"{old['error']}. With both, Claude may use either one")

    no_open = a.no_open or bool(os.environ.get("STUDIO_SETUP_NO_OPEN"))
    ok, text = ensure_key(open_editor=not no_open)
    row(ok, "KIE key", text)
    if not ok:
        problems.add("key")
    elif a.offline:
        row(True, "balance", "skipped (offline)")
    else:
        c, e = check_balance()
        if c is None:
            if e.startswith("cannot reach"):
                row(False, "balance", e + " (checked again before any video)")
            else:
                row(False, "balance", e)
                problems.add("key")
        elif c < VIDEO_CREDITS:
            row(False, "balance", f"{c:.0f} credits (${c * kie.USD_PER_CREDIT:.2f}); one video "
                                  f"needs {VIDEO_CREDITS}. Top up at https://kie.ai/billing "
                                  "($5 minimum)")
            low_balance = True
        else:
            row(True, "balance", f"{c:.0f} credits (${c * kie.USD_PER_CREDIT:.2f}) = about "
                                 f"{int(c // VIDEO_CREDITS)} video(s)")

    cok, ctext = ensure_carousel(a.offline)
    row(cok, "carousels", ctext)

    print("\n".join(rows))
    print()
    if not cok:
        print("Carousels are not ready yet (videos are not affected): " + ctext)
    if "python" in problems:
        print("NOT READY: this Python is too old. Re-run the installer from INSTALL.md; it "
              "installs a current one.")
        return 2
    if "ffmpeg" in problems:
        print("NOT READY: ffmpeg could not be downloaded. Check the internet connection and "
              "run this again. Manual fallback: macOS brew install ffmpeg, Windows winget "
              "install --id Gyan.FFmpeg -e, then restart Claude Code and run this again.")
        return 2
    if "key" in problems:
        print("ONE THING LEFT: the KIE key. Paste it into the .env file after KIE_API_KEY=, "
              "save, then run this setup again. Never paste the key into the chat."
              + (" Carousels need no key and work already; only videos wait on it." if cok else ""))
        return 1
    if low_balance:
        print("READY, but the KIE balance is under one video. Top up before making a video"
              + (" (carousels need no credits)." if cok else "."))
        return 0
    print("ALL SET.")   # the README tells Claude what to say next: the green check, then the first run
    return 0


if __name__ == "__main__":
    sys.exit(main())
