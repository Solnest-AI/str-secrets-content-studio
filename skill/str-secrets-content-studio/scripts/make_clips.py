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

Money rules (Codex review, 2026-09-28):
  * clips/_run.json is written after EVERY clip, with the KIE task id, so an interrupted
    run resumes instead of paying again: finished clips are kept, a clip whose task was
    created but never downloaded is polled again, and only the rest are generated.
  * A clip is only regenerated (a new paid task) when --only names it, or when its photo,
    prompt, length or shape changed since it was made (a fingerprint is kept per clip).
  * The dry run counts exactly the tasks the real run would create.

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
  python3 make_clips.py plan.json                generate what is missing (resumes)
  python3 make_clips.py plan.json --only 03_barn regenerate one beat (comma list ok): a new charge
  python3 make_clips.py plan.json --only ending  regenerate just the closing shot
"""
import argparse
import concurrent.futures as cf
import hashlib
import json
import pathlib
import re
import sys
import threading

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
ENDING_NAME = "zz_ending"


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
        if not NAME_OK.match(name) or name == ENDING_NAME:
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


def _sha(path):
    h = hashlib.sha1()
    try:
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(1024 * 1024), b""):
                h.update(chunk)
    except OSError:
        return "missing"
    return h.hexdigest()[:16]


def beat_fingerprint(beat, duration, aspect):
    """What a clip was made from: the photo's bytes, the prompt, the length and the shape.
    Same fingerprint = the clip on disk is still the one this plan asks for."""
    return hashlib.sha1("|".join([_sha(beat["_image"]), beat.get("prompt", ""), str(duration),
                                  aspect]).encode("utf-8")).hexdigest()[:16]


def ending_fingerprint(ending, last_clip, aspect):
    return hashlib.sha1("|".join([_sha(last_clip), ending.get("prompt", ""),
                                  str(ending.get("duration", 4)), aspect]).encode("utf-8")).hexdigest()[:16]


def classify(name, result, fingerprint, clip, explicit):
    """What to do with one clip given what _run.json remembers about it:
    'new' (create a paid task), 'keep' (done, unchanged), 'resume' (task exists, poll it)."""
    if explicit or not isinstance(result, dict):
        return "new"
    if result.get("fingerprint") != fingerprint:
        return "new"
    if result.get("ok") and clip.is_file():
        return "keep"
    if result.get("task") and result.get("state") not in ("fail",):
        return "resume"
    return "new"


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("plan")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--only", default="", help="comma list of beat names, or 'ending': "
                                                "always a new generation for those")
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
    state = {}
    if run_file.exists():
        try:
            state = json.loads(run_file.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            state = {}
    if not isinstance(state, dict):
        state = {}
    results = state.get("results") if isinstance(state.get("results"), dict) else {}
    lock = threading.Lock()

    def save():
        with lock:
            state.update({"aspect": aspect, "order": [b["name"] for b in beats],
                          "ending": ENDING_NAME if ending else None, "results": results})
            clips_dir.mkdir(parents=True, exist_ok=True)
            tmp = run_file.with_name("_run.json.tmp")
            tmp.write_text(json.dumps(state, indent=2), encoding="utf-8")
            tmp.replace(run_file)

    # decide per beat: keep what is done and unchanged, resume a task that was created
    # but never finished, generate the rest; --only always means a fresh generation
    plan_for = {}
    for b in todo:
        fp = beat_fingerprint(b, duration, aspect)
        b["_fp"] = fp
        plan_for[b["name"]] = classify(b["name"], results.get(b["name"]), fp,
                                       clips_dir / f"{b['name']}.mp4", b["name"] in only)
    new = [b for b in todo if plan_for[b["name"]] == "new"]
    resume = [b for b in todo if plan_for[b["name"]] == "resume"]
    keep = [b for b in todo if plan_for[b["name"]] == "keep"]

    ending_plan = None
    if do_ending:
        last = beats[-1]["name"]
        last_clip = clips_dir / f"{last}.mp4"
        efp = ending_fingerprint(ending, last_clip, aspect) if last_clip.is_file() else None
        ending_plan = classify(ENDING_NAME, results.get(ENDING_NAME), efp,
                               clips_dir / f"{ENDING_NAME}.mp4", "ending" in only)
        if last in plan_for and plan_for[last] == "new":
            ending_plan = "new"          # a fresh final beat means a fresh last frame

    n_new = len(new) + (1 if ending_plan == "new" else 0)
    est = n_new * VEO_CREDITS_PER_CLIP
    print(f"plan: {len(beats)} beats, aspect {aspect}, {duration}s each"
          f"{', plus a closing shot' if ending else ''}")
    for b in keep:
        print(f"  KEEP   {b['name']}  (already generated from this photo and prompt)")
    for b in resume:
        print(f"  RESUME {b['name']}  (task {results[b['name']].get('task')} was created, not "
              "finished: polling it again, no new charge)")
    if ending_plan == "keep":
        print("  KEEP   closing shot")
    elif ending_plan == "resume":
        print("  RESUME closing shot")
    print(f"this run: {n_new} new Veo generation(s) = {est} credits (${est * USD_PER_CREDIT:.2f})")

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
    save()

    def one(b):
        name = b["name"]
        prev = results.get(name) if isinstance(results.get(name), dict) else {}
        task_id = prev.get("task") if plan_for[name] == "resume" else None
        try:
            url = None if task_id else upload(b["_image"], f"{name}{b['_image'].suffix}")
            r = veo_clip(url, b["prompt"] + HOLD, clips_dir / f"{name}.mp4",
                         duration=duration, aspect=aspect, label=name, task_id=task_id)
            if r.get("ok"):
                info = probe(clips_dir / f"{name}.mp4")
                r.update({"res": f"{info['w']}x{info['h']}", "secs": round(info["secs"], 2)})
        except Exception as e:      # one bad beat must never take the whole run down
            r = {"ok": False, "task": task_id, "state": "error",
                 "error": f"{type(e).__name__}: {str(e)[:300]}"}
        r["fingerprint"] = b["_fp"]
        with lock:
            results[name] = r
        save()
        return name, r

    work = new + resume
    if work:
        print(f"\ngenerating {len(new)} clip(s)"
              f"{f' and resuming {len(resume)}' if resume else ''} in parallel "
              "(usually 2-3 minutes)...", flush=True)
        with cf.ThreadPoolExecutor(max_workers=min(MAX_WORKERS, len(work))) as pool:
            for name, r in pool.map(one, work):
                if r.get("ok"):
                    print(f"  OK    {name}  {r['secs']}s {r['res']}  ({r['seconds']}s)"
                          f"{'  resumed' if r.get('resumed') else ''}", flush=True)
                else:
                    print(f"  FAIL  {name}  {r.get('error')}", flush=True)

    if do_ending and ending_plan != "keep":
        last = beats[-1]["name"]
        last_clip = clips_dir / f"{last}.mp4"
        if not results.get(last, {}).get("ok") or not last_clip.exists():
            print(f"  SKIP  closing shot: the final beat {last} has no good clip yet")
            results[ENDING_NAME] = {"ok": False, "state": "error", "error": "final beat missing"}
            save()
        else:
            efp = ending_fingerprint(ending, last_clip, aspect)
            prev = results.get(ENDING_NAME) if isinstance(results.get(ENDING_NAME), dict) else {}
            task_id = prev.get("task") if (ending_plan == "resume" and prev.get("fingerprint") == efp) else None
            print("\n" + ("resuming" if task_id else "generating")
                  + " the closing shot from the final beat's real last frame...", flush=True)
            try:
                url = None
                if not task_id:
                    seed = last_frame(last_clip, clips_dir / "_ending_seed.jpg")
                    url = upload(seed, "ending_seed.jpg")
                r = veo_clip(url, ending["prompt"] + HOLD, clips_dir / f"{ENDING_NAME}.mp4",
                             duration=ending.get("duration", 4), aspect=aspect,
                             label="ending", task_id=task_id)
            except (KieError, MediaError) as e:
                r = {"ok": False, "task": task_id, "state": "error", "error": str(e)[:300]}
            if r.get("ok"):
                info = probe(clips_dir / f"{ENDING_NAME}.mp4")
                r.update({"res": f"{info['w']}x{info['h']}", "secs": round(info["secs"], 2)})
                print(f"  OK    closing shot  {r['secs']}s {r['res']}", flush=True)
            else:
                print(f"  FAIL  closing shot  {r.get('error')}", flush=True)
            r["fingerprint"] = efp
            results[ENDING_NAME] = r
            save()

    try:
        after = credits()
    except KieError:
        after = None
    spent = round(before - after, 1) if after is not None else None
    state["last_run"] = {"credits_before": before, "credits_after": after, "spent": spent,
                         "usd": round(spent * USD_PER_CREDIT, 2) if spent is not None else None}
    save()

    bad = [n for n in state["order"] + ([ENDING_NAME] if ending else [])
           if not results.get(n, {}).get("ok")]
    print()
    if spent is not None:
        print(f"spent this run: {spent} credits (${spent * USD_PER_CREDIT:.2f}); "
              f"balance now {after:.1f}")
    if bad:
        print(f"NOT DONE: {len(bad)} clip(s) missing: {bad}")
        print("Run the same command again first: it resumes any task that was created and "
              "only pays for what really failed. To force a fresh generation of one clip: "
              "--only " + ",".join("ending" if n == ENDING_NAME else n for n in bad))
        return 1
    print(f"ALL CLIPS READY in {clips_dir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
