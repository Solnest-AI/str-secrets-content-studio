#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# dependencies = ["pillow>=10"]
# ///
"""OPTIONAL photo polish for carousel slides: Seedream 5.0 Pro on KIE.

Off by default. Use it only when the host asks to improve a specific photo (a dark room, a
blown-out window, a crooked phone shot), and only after showing them the side-by-side and
getting a plain yes. Improving the photography is fine; inventing anything is not.

Why Seedream 5.0 Pro: in the 2026-09-26 fidelity rounds (12 models, real listing photos)
it and GPT Image 2 were the only editors that added nothing. Flux Kontext, Qwen, Seedream
4.5, Nano Banana 2 and others invented or restyled things (Nano Banana 2 swapped a living
room for a Greek villa and printed fake magazine titles on 4 of 5 photos). On already-good
photos the gain is subtle; the best win was straightening a wide-angle lean.

One run per photo, no retries (failed runs can still bill). The aspect sent is the closest
supported ratio to each original, so nothing is reframed.

Usage:
  python3 photo_fix.py source/full/16.jpg source/full/18.jpg --out source/fixed --dry-run
  python3 photo_fix.py source/full/16.jpg source/full/18.jpg --out source/fixed [--night 18]
Then LOOK at OUT/_compare.jpg (original left, fixed right) with the host. A slide uses the
fixed version only when its plan entry says "source": "fixed".
"""
import argparse
import concurrent.futures as cf
import json
import pathlib
import sys
import time

from PIL import Image, ImageDraw

import kie

MODEL = "seedream/5-pro-image-to-image"
CREDITS_PER_PHOTO = 14  # measured 2026-09-26
RATIOS = {"1:1": 1.0, "4:3": 4 / 3, "3:4": 3 / 4, "3:2": 3 / 2, "2:3": 2 / 3, "16:9": 16 / 9, "9:16": 9 / 16}
TIMEOUT = 900

BASE = (
    "Professionally edit this real-estate photograph like a high-end architectural "
    "photographer would. The input photo is the source of truth. Keep the camera position, "
    "framing and composition identical. Keep every wall, window, door, roof, railing, piece of "
    "furniture, fixture, decoration, plant, tree, person and object exactly where it is, with "
    "the same shape, size, colour and material. Do not add, remove, move, replace or restyle "
    "anything. Do not add a roof, pergola, sky replacement, grass, people, text, logo or "
    "watermark. Same time of day and same weather. Fix only the photography: balanced "
    "exposure, recover blown highlights and windows, lift muddy shadows, accurate natural "
    "colour, straight vertical lines, crisp clean detail, low noise.")
NIGHT = (" This is a sunset/dusk scene: keep the dusk light and sky colours exactly, keep the lights, "
         "do not brighten it into daytime.")


def out(msg):
    print(str(msg).encode("ascii", "replace").decode("ascii"), flush=True)


def closest_aspect(w, h):
    r = w / h
    return min(RATIOS, key=lambda k: abs(RATIOS[k] - r))


def prompt_for(night):
    return BASE + (NIGHT if night else "")


def fix_one(src, dest, night):
    t0 = time.time()
    rec = {"photo": src.name}
    try:
        w, h = Image.open(src).size
        url = kie.upload(src, name=f"fix-{src.name}")
        r = kie.call("/jobs/createTask", {"model": MODEL, "input": {
            "prompt": prompt_for(night), "image_urls": [url], "aspect_ratio": closest_aspect(w, h),
            "quality": "high", "output_format": "png"}})
        tid = r["data"]["taskId"]
        d = {}
        while time.time() - t0 < TIMEOUT:
            time.sleep(6)
            d = kie.call(f"/jobs/recordInfo?taskId={tid}").get("data") or {}
            if d.get("state") in ("success", "fail"):
                break
        rec["state"] = d.get("state") or "timeout"
        rec["task"] = tid
        if rec["state"] == "success":
            urls = kie.extract_urls(d)
            if not urls:
                raise kie.KieError(f"success but no result URL, keys={list(d.keys())}")
            kie.download(urls[0], dest, kind="image")     # checked to be a real image first
        else:
            rec["error"] = d.get("failMsg") or d.get("errorMessage") or "no result"
    except Exception as e:  # one photo failing must not stop the others
        rec["state"], rec["error"] = "error", str(e)
    rec["seconds"] = round(time.time() - t0, 1)
    out(f"  {src.name}: {rec['state']} in {rec['seconds']}s {rec.get('error', '')}")
    return rec


def compare_sheet(pairs, dest):
    """Original | fixed, one row per photo, labelled, for the host to judge."""
    rows = []
    for a, b in pairs:
        A, B = Image.open(a).convert("RGB"), Image.open(b).convert("RGB")
        h = 540
        A = A.resize((int(A.width * h / A.height), h))
        B = B.resize((int(B.width * h / B.height), h))
        r = Image.new("RGB", (A.width + B.width + 24, h + 40), "white")
        r.paste(A, (0, 40))
        r.paste(B, (A.width + 24, 40))
        d = ImageDraw.Draw(r)
        d.text((6, 10), f"{a.name}  ORIGINAL", fill="black")
        d.text((A.width + 30, 10), "SEEDREAM 5.0 PRO (check nothing was added, moved or removed)", fill="black")
        rows.append(r)
    sheet = Image.new("RGB", (max(r.width for r in rows), sum(r.height + 16 for r in rows)), "white")
    y = 0
    for r in rows:
        sheet.paste(r, (0, y))
        y += r.height + 16
    sheet.save(dest, quality=88)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("photos", nargs="+")
    ap.add_argument("--out", required=True, help="folder for the fixed photos (source/fixed)")
    ap.add_argument("--night", default="", help="comma-separated photo ids that are dusk/night shots")
    ap.add_argument("--dry-run", action="store_true", help="show cost and balance, spend nothing")
    a = ap.parse_args(argv)
    srcs = [pathlib.Path(p) for p in a.photos]
    missing = [str(p) for p in srcs if not p.exists()]
    if missing:
        out(f"ERROR: not found: {missing}")
        return 2
    night = {x.strip() for x in a.night.split(",") if x.strip()}
    cost = CREDITS_PER_PHOTO * len(srcs)
    try:
        bal = kie.credits()
    except kie.KieError as e:
        out(f"ERROR: {e}")
        return 2
    out(f"{len(srcs)} photos x {CREDITS_PER_PHOTO} = {cost} credits (${cost * kie.USD_PER_CREDIT:.2f}); "
        f"balance {bal:.0f} credits")
    if bal < cost:
        out("ERROR: not enough KIE credits. Top up at kie.ai, or fix fewer photos.")
        return 2
    if a.dry_run:
        out("Dry run: nothing spent.")
        return 0
    dest = pathlib.Path(a.out)
    dest.mkdir(parents=True, exist_ok=True)
    with cf.ThreadPoolExecutor(max_workers=4) as ex:
        recs = list(ex.map(lambda p: fix_one(p, dest / f"{p.stem}.png", p.stem in night), srcs))
    time.sleep(10)
    try:
        spent = round(bal - kie.credits(), 2)
    except kie.KieError:
        spent = None
    done = [(p, dest / f"{p.stem}.png") for p, r in zip(srcs, recs) if r["state"] == "success"]
    if done:
        compare_sheet(done, dest / "_compare.jpg")
    (dest / "_run.json").write_text(json.dumps({"model": MODEL, "credits_spent": spent, "tasks": recs}, indent=1),
                                    encoding="utf-8")
    out(f"{len(done)}/{len(srcs)} fixed, {spent} credits spent. LOOK at {dest / '_compare.jpg'} with the host; "
        "use a fixed photo only if nothing was added, moved or removed and they say yes.")
    return 0 if done else 1


if __name__ == "__main__":
    sys.exit(main())
