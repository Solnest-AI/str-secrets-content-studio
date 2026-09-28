#!/usr/bin/env python3
"""Generate every clip for one walkthrough on KIE Veo 3.1, from a plan file.

The recipe (measured on the Langley and Sun Peaks test runs, 2026-09-20/21):
  * ONE anchor per clip. A last frame is never supplied, so nothing cross-dissolves and
    the model never invents a path to an unseen destination.
  * A full scene description in every prompt, not motion only.
  * Architecture held rigid by a fixed suffix appended to every prompt (HOLD below).
  * Joins between beats are free ffmpeg crossfades at assembly, never generated bridges.
  * Optional closing shot seeded from the final beat's TRUE last frame, so it continues
    the take seamlessly with a hard cut (the only chaining that survived testing).

plan.json (paths are relative to the plan file):
  {
    "aspect": "9:16",               9:16 reels, 16:9 website/owner email, 1:1
    "duration": 6,                  seconds per beat: 4, 6 or 8 (same price)
    "beats": [
      {"name": "01_living", "image": "crops/01.jpg",
       "prompt": "<what is in the photo> + <one slow camera move toward something in it>"}
    ],
    "ending": {"prompt": "<same scene> + the camera drifts slowly backward ...",
               "duration": 4}          optional
  }

Usage:
  python3 make_clips.py plan.json --dry-run      check the plan, cost and balance
  python3 make_clips.py plan.json                generate everything
  python3 make_clips.py plan.json --only 03_barn regenerate one beat (comma list ok)
  python3 make_clips.py plan.json --only ending  regenerate just the closing shot
"""
import argparse
import concurrent.futures as cf
import json
import pathlib
import re
import sys

from kie import (USD_PER_CREDIT, VEO_CREDITS_PER_CLIP, VEO_DURATIONS, KieError, credits,
                 find_key, upload, veo_clip)
from media import ASPECTS, MediaError, last_frame, probe

HOLD = (" Walls, ceilings, window frames, cabinetry, railings and furniture stay rigid and "
        "never warp, bend, ripple or melt. Straight lines stay straight and verticals stay "
        "vertical. Natural daylight, true colour, realistic depth of field, smooth steadicam "
        "movement at one constant unhurried pace, one unbroken take. Live-action real estate "
        "cinematography. No people, no animals, no text, no logos, no jump cuts, no zoom snaps.")

NAME_OK = re.compile(r"^[A-Za-z0-9_-]{1,40}$")
MAX_WORKERS = 6            # KIE allows ~20 new requests per 10s; stay well under


def load_plan(path):
    plan_path = pathlib.Path(path).resolve()
    base = plan_path.parent
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    errors = []
    aspect = plan.get("aspect", "9:16")
    if aspect not in ASPECTS:
        errors.append(f"aspect must be one of {sorted(ASPECTS)}, got {aspect!r}")
    duration = plan.get("duration", 6)
    if duration not in VEO_DURATIONS:
        errors.append(f"duration must be one of {VEO_DURATIONS}, got {duration!r}")
    beats = plan.get("beats") or []
    if not 1 <= len(beats) <= 8:
        errors.append(f"need 1 to 8 beats, got {len(beats)}")
    seen = set()
    for i, b in enumerate(beats, 1):
        name = b.get("name", "")
        if not NAME_OK.match(name):
            errors.append(f"beat {i}: name {name!r} must be letters, numbers, _ or -")
        if name in seen:
            errors.append(f"beat {i}: duplicate name {name!r}")
        seen.add(name)
        img = base / b.get("image", "")
        if not b.get("image") or not img.is_file():
            errors.append(f"beat {i} ({name}): image not found: {img}")
        if len(b.get("prompt", "")) < 60:
            errors.append(f"beat {i} ({name}): prompt too short. Describe the room AND the "
                          "one camera move.")
        b["_image"] = img
    images = [str(b["_image"]) for b in beats]
    if len(images) != len(set(images)):
        errors.append("the same photo is used twice. Every beat needs its own photo.")
    ending = plan.get("ending")
    if ending:
        if len(ending.get("prompt", "")) < 60:
            errors.append("ending: prompt too short")
        if ending.get("duration", 4) not in VEO_DURATIONS:
            errors.append(f"ending: duration must be one of {VEO_DURATIONS}")
    if errors:
        raise ValueError("plan problems:\n  - " + "\n  - ".join(errors))
    return plan, base, aspect, duration, beats, ending


def select_work(beats, ending, only):
    """Which beats to generate, and whether the closing shot is. Redoing the final beat
    always redoes the closing shot too: it is seeded from that beat's last frame."""
    todo = [b for b in beats if not only or b["name"] in only]
    do_ending = bool(ending) and (not only or "ending" in only)
    note = ""
    if ending and only and beats and beats[-1]["name"] in only and "ending" not in only:
        do_ending = True
        note = (f"note: {beats[-1]['name']} is the final beat, so the closing shot is "
                "regenerated too (it is seeded from that beat's last frame)")
    return todo, do_ending, note


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("plan")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--only", default="", help="comma list of beat names, or 'ending'")
    a = ap.parse_args(argv)

    try:
        plan, base, aspect, duration, beats, ending = load_plan(a.plan)
    except (ValueError, OSError, json.JSONDecodeError) as e:
        print(f"ERROR: {e}")
        return 1

    only = {s.strip() for s in a.only.split(",") if s.strip()}
    unknown = only - {b["name"] for b in beats} - {"ending"}
    if unknown:
        print(f"ERROR: --only names not in the plan: {sorted(unknown)}")
        return 1
    todo, do_ending, note = select_work(beats, ending, only)
    if note:
        print(note)

    clips_dir = base / "clips"
    run_file = clips_dir / "_run.json"
    n_gen = len(todo) + (1 if do_ending else 0)
    est = n_gen * VEO_CREDITS_PER_CLIP
    print(f"plan: {len(beats)} beats, aspect {aspect}, {duration}s each"
          f"{', plus a closing shot' if ending else ''}")
    print(f"this run: {n_gen} Veo generations = {est} credits (${est * USD_PER_CREDIT:.2f})")

    try:
        _, where = find_key()
        before = credits()
    except KieError as e:
        print(f"ERROR: {e}")
        return 1
    print(f"KIE key from: {where}")
    print(f"balance: {before:.1f} credits (${before * USD_PER_CREDIT:.2f})")
    if before < est:
        print(f"ERROR: not enough credits for this run. Need {est}, have {before:.0f}. "
              "Top up at https://kie.ai/billing")
        return 1
    if a.dry_run:
        print("DRY RUN OK: plan is valid and the balance covers it. Nothing was spent.")
        return 0

    clips_dir.mkdir(parents=True, exist_ok=True)
    state = {}
    if run_file.exists():
        try:
            state = json.loads(run_file.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            state = {}
    results = state.get("results", {})

    def one(b):
        name = b["name"]
        try:
            url = upload(b["_image"], f"{name}{b['_image'].suffix}")
            r = veo_clip(url, b["prompt"] + HOLD, clips_dir / f"{name}.mp4",
                         duration=duration, aspect=aspect, label=name)
            if r.get("ok"):
                info = probe(clips_dir / f"{name}.mp4")
                r.update({"res": f"{info['w']}x{info['h']}", "secs": round(info["secs"], 2)})
            return name, r
        except Exception as e:      # one bad beat must never take the whole run down
            return name, {"ok": False, "error": f"{type(e).__name__}: {str(e)[:300]}"}

    if todo:
        print(f"\ngenerating {len(todo)} clip(s) in parallel (usually 2-3 minutes)...",
              flush=True)
        with cf.ThreadPoolExecutor(max_workers=min(MAX_WORKERS, len(todo))) as pool:
            for name, r in pool.map(one, todo):
                results[name] = r
                if r.get("ok"):
                    print(f"  OK    {name}  {r['secs']}s {r['res']}  ({r['seconds']}s)",
                          flush=True)
                else:
                    print(f"  FAIL  {name}  {r.get('error')}", flush=True)

    ending_name = None
    if ending:
        ending_name = "zz_ending"
    if do_ending:
        last = beats[-1]["name"]
        last_clip = clips_dir / f"{last}.mp4"
        if not results.get(last, {}).get("ok") or not last_clip.exists():
            print(f"  SKIP  closing shot: the final beat {last} has no good clip yet")
            results[ending_name] = {"ok": False, "error": "final beat missing"}
        else:
            print("\ngenerating the closing shot from the final beat's real last frame...",
                  flush=True)
            try:
                seed = last_frame(last_clip, clips_dir / "_ending_seed.jpg")
                url = upload(seed, "ending_seed.jpg")
                r = veo_clip(url, ending["prompt"] + HOLD, clips_dir / f"{ending_name}.mp4",
                             duration=ending.get("duration", 4), aspect=aspect,
                             label="ending")
            except (KieError, MediaError) as e:
                r = {"ok": False, "error": str(e)[:300]}
            if r.get("ok"):
                info = probe(clips_dir / f"{ending_name}.mp4")
                r.update({"res": f"{info['w']}x{info['h']}", "secs": round(info["secs"], 2)})
                print(f"  OK    closing shot  {r['secs']}s {r['res']}", flush=True)
            else:
                print(f"  FAIL  closing shot  {r.get('error')}", flush=True)
            results[ending_name] = r

    try:
        after = credits()
    except KieError:
        after = None
    spent = round(before - after, 1) if after is not None else None
    state.update({
        "aspect": aspect,
        "order": [b["name"] for b in beats],
        "ending": ending_name,
        "results": results,
        "last_run": {"credits_before": before, "credits_after": after, "spent": spent,
                     "usd": round(spent * USD_PER_CREDIT, 2) if spent is not None else None},
    })
    run_file.write_text(json.dumps(state, indent=2), encoding="utf-8")

    bad = [n for n in state["order"] + ([ending_name] if ending_name else [])
           if not results.get(n, {}).get("ok")]
    print()
    if spent is not None:
        print(f"spent this run: {spent} credits (${spent * USD_PER_CREDIT:.2f}); "
              f"balance now {after:.1f}")
    if bad:
        retry = ",".join("ending" if n == ending_name else n for n in bad)
        print(f"NOT DONE: {len(bad)} clip(s) missing: {bad}")
        print(f"Re-run just those with:  --only {retry}")
        return 1
    print(f"ALL CLIPS READY in {clips_dir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
