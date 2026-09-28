#!/usr/bin/env python3
"""KIE.ai client for the STR Secrets Content Studio. Python stdlib only.

Every guard here exists because something bit us in testing (2026-09-20/21) or is a
documented KIE failure mode:

  * KIE returns HTTP 200 even when auth FAILS  -> always branch on body["code"]
  * result URLs live in 3 different shapes     -> try all of them
  * generated media expires after ~14 days     -> download immediately
  * failed generations sometimes still bill    -> measure credits before/after
  * a job can sit "generating" forever         -> hard timeout, never poll forever
  * rate limit ~20 new requests / 10s          -> small worker pool + jittered backoff
  * upload docs say fileUrl, the API returns downloadUrl -> accept both
  * ONE paid task per clip, ever (Codex review 2026-09-28): a failed poll or download is
    retried against the SAME task; a second task is only created when Claude asks for a
    redo explicitly (make_clips.py --only). Downloads land in a .part file and are checked
    to be real media before they replace anything.

Output is ASCII only, so it cannot crash a Windows console with an encoding error.

Run directly for a balance check:  python3 kie.py --balance
"""
import base64
import json
import os
import pathlib
import random
import shutil
import sys
import time
import urllib.error
import urllib.request

for _stream in (sys.stdout, sys.stderr):      # see media.py: never crash on a non-Latin path
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

API = "https://api.kie.ai/api/v1"
UPLOAD_URL = "https://kieai.redpandaai.co/api/file-base64-upload"
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36")
USD_PER_CREDIT = 0.005

# Veo 3.1 bills a flat 65 credits ($0.325) per generation at 4, 6 or 8 seconds
# (measured 2026-09-21). Longer clips cost nothing extra.
VEO_SLUG = "veo-3-1"
VEO_CREDITS_PER_CLIP = 65
VEO_DURATIONS = (4, 6, 8)

IMAGE_MAGIC = (b"\xff\xd8", b"\x89PNG", b"RIFF")
MIN_MEDIA_BYTES = {"video": 20000, "image": 1000}

SKILL_DIR = pathlib.Path(__file__).resolve().parent.parent


class KieError(RuntimeError):
    pass


def _read_env_file(path):
    vals = {}
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                s = line.strip()
                if s and not s.startswith("#") and "=" in s:
                    k, v = s.split("=", 1)
                    vals[k.strip()] = v.strip().strip('"').strip("'")
    except OSError:
        pass
    return vals


KIT_FOLDER = "str-secrets-connections"


def kit_env_paths():
    """Where the STR Secrets Connections kit keeps the attendee's .env. The kit registers
    its `kie` server in ~/.claude.json with KIE_ENV_PATH pointing at that file; the usual
    folders are scanned too, in case the server was never registered."""
    out = []
    home = pathlib.Path.home()
    try:
        data = json.loads((home / ".claude.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        data = {}
    if not isinstance(data, dict):
        data = {}
    servers = list((data.get("mcpServers") or {}).values())
    for proj in (data.get("projects") or {}).values():
        if isinstance(proj, dict):
            servers += list((proj.get("mcpServers") or {}).values())
    for spec in servers:
        env = spec.get("env") if isinstance(spec, dict) else None
        p = (env or {}).get("KIE_ENV_PATH")
        if isinstance(p, str) and p:
            out.append(pathlib.Path(p))
    for base in (home / "Desktop", home / "Documents", home / "Downloads",
                 home / "OneDrive" / "Desktop", home / "OneDrive" / "Documents", home):
        try:
            for pattern in (f"{KIT_FOLDER}*", f"*/{KIT_FOLDER}*"):
                out += [d / ".env" for d in sorted(base.glob(pattern)) if d.is_dir()]
        except OSError:
            pass
    seen, uniq = set(), []
    for p in out:
        if str(p) not in seen:
            seen.add(str(p))
            uniq.append(p)
    return uniq


def key_search_paths():
    return ([SKILL_DIR / ".env", pathlib.Path.cwd() / ".env", pathlib.Path.home() / ".env"]
            + kit_env_paths())


def find_key():
    """Return (key, where_it_came_from). Never prints the key."""
    k = os.environ.get("KIE_API_KEY", "").strip()
    if k:
        return k, "KIE_API_KEY environment variable"
    for p in key_search_paths():
        k = _read_env_file(p).get("KIE_API_KEY", "")
        if k:
            return k, str(p)
    looked = "\n  ".join(str(p) for p in key_search_paths())
    raise KieError(
        "No KIE_API_KEY found. Get one at https://kie.ai/api-key and add this line to "
        f"{SKILL_DIR / '.env'}:\n  KIE_API_KEY=your_key_here\nPlaces checked:\n  {looked}")


_HEADERS = None


def headers():
    global _HEADERS
    if _HEADERS is None:
        key, _ = find_key()
        _HEADERS = {"Authorization": f"Bearer {key}", "Content-Type": "application/json",
                    "User-Agent": UA, "Accept": "application/json"}
    return _HEADERS


def call(path, body=None, timeout=120):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(API + path, data=data, headers=headers(),
                                 method="POST" if body is not None else "GET")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw = r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        raise KieError(f"HTTP {e.code} from KIE {path}") from e
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        raise KieError(f"cannot reach KIE at api.kie.ai ({getattr(e, 'reason', e)}). "
                       "Check the internet connection and try again.") from e
    try:
        payload = json.loads(raw)
    except ValueError as e:
        raise KieError(f"KIE {path} answered with something that is not JSON "
                       f"({raw[:80]!r}). Try again in a minute.") from e
    if not isinstance(payload, dict):
        raise KieError(f"KIE {path} answered with unexpected JSON")
    # The whole point: HTTP 200 does NOT mean success. The real status is in the body.
    code = payload.get("code")
    if code not in (200, None):
        hint = " (the API key is wrong or revoked)" if code in (401, 403) else ""
        hint = " (the KIE account is out of credits)" if code == 402 else hint
        raise KieError(f"KIE code={code} msg={payload.get('msg')}{hint}")
    return payload


def transient(err):
    """True for errors worth retrying against the same task: no answer from KIE at all."""
    s = str(err)
    return s.startswith("cannot reach") or "not JSON" in s or s.startswith("HTTP 5")


def credits():
    """The account balance in credits. KIE answers {"data": 123.0}; a dict is tolerated."""
    data = call("/chat/credit").get("data")
    if isinstance(data, dict):
        data = data.get("credits", data.get("balance"))
    try:
        return float(data)
    except (TypeError, ValueError):
        raise KieError(f"KIE /chat/credit answered with an unexpected balance: {str(data)[:80]!r}")


def upload(path, name=None):
    """Host a local image on KIE so a video model can read it. Returns the URL."""
    p = pathlib.Path(path)
    ext = p.suffix.lower().lstrip(".")
    mime = {"jpg": "jpeg", "jpeg": "jpeg", "png": "png", "webp": "webp"}.get(ext, "jpeg")
    b64 = base64.b64encode(p.read_bytes()).decode()
    body = json.dumps({"base64Data": f"data:image/{mime};base64,{b64}",
                       "uploadPath": "images", "fileName": name or p.name}).encode()
    req = urllib.request.Request(UPLOAD_URL, data=body, headers=headers(), method="POST")
    last = None
    for attempt in range(1, 4):
        try:
            with urllib.request.urlopen(req, timeout=240) as r:
                d = json.loads(r.read().decode("utf-8")).get("data") or {}
            url = d.get("downloadUrl") or d.get("fileUrl") if isinstance(d, dict) else None
            if url:
                return url
            last = KieError(f"upload returned no URL, keys={list(d.keys()) if isinstance(d, dict) else d}")
        except (urllib.error.URLError, TimeoutError, OSError, ValueError) as e:
            last = e
        time.sleep(3 * attempt + random.uniform(0, 2))
    raise KieError(f"upload failed for {p.name}: {last}")


def extract_urls(record):
    """KIE returns result URLs in at least three different shapes. Never raises."""
    if not isinstance(record, dict):
        return []
    rj = record.get("resultJson")
    try:
        d = json.loads(rj) if isinstance(rj, str) else (rj or {})
    except ValueError:
        return []
    if not isinstance(d, dict):
        return []
    if isinstance(d.get("resultUrls"), list) and d["resultUrls"]:
        return d["resultUrls"]
    inner = d.get("data") or {}
    if isinstance(inner, dict):
        for key in ("result_urls", "resultUrls", "origin_urls"):
            if isinstance(inner.get(key), list) and inner[key]:
                return inner[key]
    return []


def looks_like_media(path, kind):
    """First bytes of a real MP4/MOV ('ftyp' at offset 4) or a real JPEG/PNG/WEBP."""
    with open(path, "rb") as f:
        head = f.read(16)
    if kind == "video":
        return head[4:8] == b"ftyp"
    return head.startswith(IMAGE_MAGIC)


def download(url, dest, kind="video", tries=3):
    """Download a result to dest. It goes to a .part file first and is checked to be real
    media of the right kind and size before it replaces dest, so a truncated transfer or
    an HTML error page can never pass as a clip or a photo. Retries the download only;
    nothing here can create a task."""
    dest = pathlib.Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    part = dest.with_name(dest.name + ".part")
    last = None
    for attempt in range(1, tries + 1):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=300) as r, open(part, "wb") as f:
                shutil.copyfileobj(r, f, 1024 * 1024)
            size = part.stat().st_size
            if size < MIN_MEDIA_BYTES.get(kind, 1000):
                raise KieError(f"downloaded only {size} bytes")
            if not looks_like_media(part, kind):
                raise KieError(f"the download is not a {kind} file")
            part.replace(dest)
            return size
        except (KieError, urllib.error.URLError, TimeoutError, OSError) as e:
            last = e
            try:
                part.unlink()
            except OSError:
                pass
            if attempt < tries:
                time.sleep(2 * attempt + random.uniform(0, 1))
    raise KieError(f"download failed after {tries} tries: {last}")


def create_task(body):
    """Exactly one createTask call. It is never retried: a timeout may mean the task was
    created (and billed) even though no answer arrived, and the caller has no way to tell."""
    r = call("/jobs/createTask", body)
    data = r.get("data")
    tid = data.get("taskId") if isinstance(data, dict) else None
    if not tid:
        raise KieError(f"no taskId in KIE's answer: {str(r)[:200]}")
    return str(tid)


def wait_task(tid, max_wait=900, poll=6):
    """Poll ONE task until it succeeds or fails. Network hiccups while polling are retried
    until the deadline. Returns (state, record); raises KieError on timeout or a real
    KIE error (bad key, ...). Never creates a task."""
    deadline = time.time() + max_wait
    state, rec, last_err = None, {}, None
    while time.time() < deadline:
        time.sleep(poll)
        try:
            data = call(f"/jobs/recordInfo?taskId={tid}").get("data")
        except KieError as e:
            if transient(e):
                last_err = e
                continue
            raise
        rec = data if isinstance(data, dict) else {}
        state = rec.get("state")
        if state in ("success", "fail"):
            return state, rec
    raise KieError(f"task {tid} still '{state}' after {max_wait}s"
                   + (f" (last error: {last_err})" if last_err else "")
                   + "; credits may still be charged. Re-run with --only to resume it.")


def veo_clip(image_url, prompt, dest, *, duration=6, aspect="9:16", resolution="1080p",
             max_wait=900, label="", task_id=None):
    """One Veo 3.1 clip from ONE start image. Never pass a last frame: two anchors
    make the model cross-dissolve into the end image and invent the gap (measured on
    Veo, Kling and PixVerse, 2026-09-20). Veo cannot turn audio off; the assembler
    drops it.

    Money rule: this creates at most ONE paid task (none when task_id is given: that
    resumes an earlier one). A failed poll or download is retried against that same
    task. Anything unrecoverable comes back as {"ok": False, "task": tid, ...} so the
    caller can save the task id and Claude can decide, explicitly, to spend again."""
    if duration not in VEO_DURATIONS:
        raise KieError(f"Veo duration must be one of {VEO_DURATIONS}, got {duration}")
    t0 = time.time()
    tid = task_id
    try:
        if not tid:
            tid = create_task({"model": VEO_SLUG, "input": {
                "prompt": prompt, "image_urls": [image_url],        # ONE anchor, always
                "generation_type": "FIRST_AND_LAST_FRAMES_2_VIDEO",
                "duration": duration, "resolution": resolution, "aspect_ratio": aspect}})
        state, rec = wait_task(tid, max_wait)
        if state != "success":
            return {"ok": False, "task": tid, "state": "fail",
                    "error": f"generation failed: {rec.get('failMsg') or rec.get('errorMessage')}"}
        urls = extract_urls(rec)
        if not urls:
            return {"ok": False, "task": tid, "state": "success",
                    "error": f"success but no result URL, keys={list(rec.keys())}"}
        size = download(urls[0], dest, kind="video")     # ~14-day expiry: grab it now
        return {"ok": True, "task": tid, "state": "success", "resumed": bool(task_id),
                "seconds": round(time.time() - t0, 1), "bytes": size, "file": str(dest)}
    except KieError as e:
        print(f"  {label} failed: {e}", flush=True)
        return {"ok": False, "task": tid, "state": "error", "error": str(e)[:300]}


if __name__ == "__main__":
    if "--balance" in sys.argv:
        try:
            _, where = find_key()
            c = credits()
        except KieError as e:
            print(f"ERROR: {e}")
            sys.exit(1)
        print(f"KIE key found in: {where}")
        print(f"Balance: {c:.1f} credits (${c * USD_PER_CREDIT:.2f})")
        print(f"That covers about {int(c // VEO_CREDITS_PER_CLIP)} Veo clips.")
        sys.exit(0)
    print(__doc__)
