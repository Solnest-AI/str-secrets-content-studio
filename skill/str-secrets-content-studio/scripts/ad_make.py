#!/usr/bin/env python3
"""Clone a static ad or a carousel card for the host's own brand, on KIE with the same key the
videos use. Python stdlib only. Images only: static posts and carousel cards.

GPT Image 2 on KIE writes on-image text best of the models tested (the clone-ad bake-off).
With --ref it edits from references: the competitor's ad as the layout blueprint, and the
host's real listing photo as the hero. Without --ref it builds the frame from the spec alone.

Money rules (same as make_clips.py): the price is printed and checked against the balance
before anything is sent; --dry-run stops there; each image is one task; a task KIE fails on
its own side is retried with a fresh task up to twice (those failures are not billed); every
task id is saved in OUT/_ads.json so a rerun keeps what is done instead of paying again.

Usage:
  <py> ad_make.py --spec spec.txt --ref competitor.jpg --ref listing-photo.jpg --aspect 4:5 --out ads/made --name hook1
  <py> ad_make.py --spec spec.txt --aspect 1:1 --count 3 --out ads/made --name idea2
  <py> ad_make.py ... --dry-run          the price and the balance, nothing spent
A carousel is one call per card (--name card1, card2, ...), each with that card as --ref.
"""
import argparse
import json
import pathlib
import sys
import time

import kie

CREDITS_PER_IMAGE = 6                      # GPT Image 2 on KIE, measured 2026-09-28
MODEL_T2I = "gpt-image-2-text-to-image"
MODEL_EDIT = "gpt-image-2-image-to-image"
ASPECTS = ("1:1", "4:5", "9:16", "16:9", "3:4", "2:3", "3:2")
KIE_FAIL_RETRIES = 2


class AdError(RuntimeError):
    pass


def load_state(out):
    try:
        return json.loads((out / "_ads.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def save_state(out, state):
    out.mkdir(parents=True, exist_ok=True)
    tmp = out / "_ads.json.tmp"
    tmp.write_text(json.dumps(state, indent=1), encoding="utf-8")
    tmp.replace(out / "_ads.json")


def run_task(out, state, key, body, dest):
    """One image = one task. Keeps a finished one, resumes a created one, and retries only
    failures KIE reports on its own side (not billed)."""
    prev = state.get(key) or {}
    if prev.get("ok") and pathlib.Path(prev.get("file", "")).is_file():
        print(f"  KEEP  {key}  ({prev['file']})")
        return prev
    tid = prev.get("task") if prev.get("state") == "created" else None
    rec = {}
    for attempt in range(KIE_FAIL_RETRIES + 1):
        if not tid:
            tid = kie.create_task(body)
            state[key] = {"task": tid, "state": "created"}
            save_state(out, state)
        st, rec = kie.wait_task(tid, max_wait=900, poll=6)
        if st == "success":
            urls = kie.extract_urls(rec)
            if not urls:
                raise AdError(f"{key}: KIE said success but sent no file")
            kie.download(urls[0], dest, kind="image")
            state[key] = {"task": tid, "state": "success", "ok": True, "file": str(dest)}
            save_state(out, state)
            print(f"  OK    {key}  -> {dest}")
            return state[key]
        state[key] = {"task": tid, "state": "fail", "error": rec.get("failMsg")}
        save_state(out, state)
        if attempt < KIE_FAIL_RETRIES:
            print(f"  {key}: KIE failed it on their side ({rec.get('failMsg')}); not billed, "
                  f"trying again ({attempt + 1} of {KIE_FAIL_RETRIES})", flush=True)
            tid = None
            time.sleep(5)
    raise AdError(f"{key}: KIE failed it {KIE_FAIL_RETRIES + 1} times ({rec.get('failMsg')}); "
                  "nothing was billed for those. Try again in a few minutes.")


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--spec", required=True, help="text file with the full ad spec (see ADS.md step 4)")
    ap.add_argument("--ref", action="append", default=[],
                    help="reference image (repeatable, order matters): the blueprint ad, then the hero photo")
    ap.add_argument("--aspect", default="1:1", choices=ASPECTS)
    ap.add_argument("--count", type=int, default=1, choices=[1, 2, 3])
    ap.add_argument("--out", required=True)
    ap.add_argument("--name", required=True, help="file name stem: letters, numbers, _ or -")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args(argv)
    if not all(c.isalnum() or c in "_-" for c in a.name):
        ap.error("--name: letters, numbers, _ or - only")
    out = pathlib.Path(a.out)
    try:
        spec = pathlib.Path(a.spec).read_text(encoding="utf-8").strip()
        if len(spec) < 80:
            raise AdError("the spec is too short: describe every text zone, the layout and the hero (ADS.md step 4)")
        refs = [pathlib.Path(r) for r in a.ref]
        missing = [str(r) for r in refs if not r.is_file()]
        if missing:
            raise AdError(f"reference not found: {missing}")
        state = load_state(out)
        todo = [n for n in range(1, a.count + 1)
                if not (state.get(f"{a.name}_{n}", {}).get("ok")
                        and pathlib.Path(state[f"{a.name}_{n}"].get("file", "")).is_file())]
        cost = CREDITS_PER_IMAGE * len(todo)
        bal = kie.credits()
        print(f"this run: {len(todo)} image(s) = {cost} credits (USD {cost * kie.USD_PER_CREDIT:.2f}); "
              f"balance {bal:.0f} credits")
        if bal < cost:
            raise AdError(f"not enough KIE credits: need {cost}, have {bal:.0f}. Top up at https://kie.ai/billing")
        if a.dry_run:
            print("DRY RUN OK: nothing was spent.")
            return 0
        urls = [kie.upload(r, r.name) for r in refs]
        inp = {"prompt": f"{spec}\nAspect ratio {a.aspect}.", "aspect_ratio": a.aspect}
        if urls:
            inp["input_urls"] = urls
        body = {"model": MODEL_EDIT if urls else MODEL_T2I, "input": inp}
        made = 0
        for n in range(1, a.count + 1):
            try:
                run_task(out, state, f"{a.name}_{n}", body, out / f"{a.name}_{n}.png")
                made += 1
            except (AdError, kie.KieError) as e:
                print(f"  FAIL  {e}")
        print(f"{made}/{a.count} image(s) in {out}")
        return 0 if made == a.count else 1
    except (AdError, kie.KieError, OSError) as e:
        print(f"ERROR: {e}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
