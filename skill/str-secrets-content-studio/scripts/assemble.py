#!/usr/bin/env python3
"""Assemble the generated clips into the finished walkthrough. Python stdlib + ffmpeg.

Timeline (the Langley recipe, 2026-09-21):
  * every beat except the last is trimmed to --trim seconds (default 4.6)
  * beats join with --xfade second crossfades (default 0.6), free and clean
  * the LAST beat plays in full, because the closing shot was seeded from its true
    final frame and trimming it would put a jump right before the seamless continue
  * the closing shot, if there is one, follows with a hard cut
  * all generated audio is dropped (Veo cannot turn it off); an optional music bed goes
    under the whole thing with a fade in and out

  6 beats + closing: 5 x 4.6 + 6.0 - 5 x 0.6 + 4.0 = 30.0s
  5 beats + closing: 4 x 4.6 + 6.0 - 4 x 0.6 + 4.0 = 26.0s

Usage:
  python3 assemble.py CLIPS_DIR --out final/walkthrough-9x16.mp4 [--music bed.mp3]
Reads the beat order from CLIPS_DIR/_run.json (written by make_clips.py).
"""
import argparse
import json
import pathlib
import sys

from media import ASPECTS, MediaError, probe, run, tool

FPS = 24


def timeline(durs, trim, xfade, ending_secs=0.0):
    """Return (per-clip lengths used, xfade offsets, total seconds). Pure, testable."""
    n = len(durs)
    used = [min(trim, d) for d in durs[:-1]] + [durs[-1]]
    offsets, run_len = [], used[0]
    for i in range(1, n):
        offsets.append(round(run_len - xfade, 3))
        run_len = run_len + used[i] - xfade
    return used, offsets, round(run_len + ending_secs, 3)


def stale_clips(cdir, order, results):
    """Beats whose clip was made from something other than what plan.json says now (a
    changed photo, prompt, length or shape), so the video would not match the plan.
    Empty when there is no plan.json beside the clips or no fingerprints were recorded."""
    plan_file = cdir.parent / "plan.json"
    if not plan_file.is_file():
        return []
    try:
        import make_clips
        _, _, aspect, duration, beats, _ = make_clips.load_plan(plan_file)
    except Exception:
        return []
    stale = []
    for b in beats:
        if b["name"] not in order:
            continue
        r = results.get(b["name"]) or {}
        fp = r.get("fingerprint")
        if fp and fp != make_clips.beat_fingerprint(b, duration, aspect):
            stale.append(b["name"])
    return stale


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("clips_dir")
    ap.add_argument("--out", required=True)
    ap.add_argument("--music", default="")
    ap.add_argument("--music-vol", type=float, default=0.85)
    ap.add_argument("--trim", type=float, default=4.6)
    ap.add_argument("--xfade", type=float, default=0.6)
    ap.add_argument("--no-preview", action="store_true",
                    help="skip the small VIEW-*.mp4 preview copy")
    ap.add_argument("--without-ending", action="store_true",
                    help="ship without the closing shot even though the plan has one")
    a = ap.parse_args(argv)

    cdir = pathlib.Path(a.clips_dir)
    try:
        state = json.loads((cdir / "_run.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        print(f"ERROR: cannot read {cdir / '_run.json'} ({e}). Run make_clips.py first.")
        return 1
    order, results = state.get("order", []), state.get("results", {})
    missing = [n for n in order if not results.get(n, {}).get("ok")
               or not (cdir / f"{n}.mp4").is_file()]
    if missing:
        print(f"ERROR: clips not ready: {missing}. Run make_clips.py again (it resumes), or "
              "--only to regenerate")
        return 1
    stale = stale_clips(cdir, order, results)
    if stale:
        print(f"ERROR: {stale} were generated from a different photo, prompt, length or shape "
              "than plan.json has now. Run make_clips.py again so the video matches the plan.")
        return 1
    ending = state.get("ending")
    end_clip = cdir / f"{ending}.mp4" if ending else None
    if end_clip and not (results.get(ending, {}).get("ok") and end_clip.is_file()):
        if not a.without_ending:
            print("ERROR: the plan has a closing shot but it is not ready. Run make_clips.py "
                  "again (it resumes or regenerates it), or pass --without-ending to ship "
                  "the video without it on purpose.")
            return 1
        print("NOTE: shipping without the closing shot, as asked.")
        end_clip = None
    music = pathlib.Path(a.music) if a.music else None
    if music and not music.is_file():
        print(f"ERROR: music file not found: {music}")
        return 1

    try:
        w, h = ASPECTS[state.get("aspect", "9:16")]
        clips = [cdir / f"{n}.mp4" for n in order]
        durs = [probe(c)["secs"] for c in clips]
        end_secs = probe(end_clip)["secs"] if end_clip else 0.0
        if len(clips) > 1 and min(durs[:-1]) <= a.xfade:
            print(f"ERROR: a clip is shorter than the {a.xfade}s crossfade")
            return 1
        used, offsets, total = timeline(durs, a.trim, a.xfade, end_secs)

        # explicit fit factor: force_original_aspect_ratio=decrease can round up a pixel
        # and then pad refuses (see sheet.py); a clip one pixel off would kill the render
        fit = f"min({w}/iw\\,{h}/ih)"
        norm = (f"scale=iw*{fit}:ih*{fit},"
                f"pad={w}:{h}:(ow-iw)/2:(oh-ih)/2:color=black,setsar=1,fps={FPS},"
                "format=yuv420p")
        cmd = [tool("ffmpeg"), "-y", "-v", "error"]
        for c, u in zip(clips, used):
            cmd += ["-t", f"{u:.3f}", "-i", str(c)]
        idx = len(clips)
        if end_clip:
            cmd += ["-i", str(end_clip)]
            end_idx, idx = idx, idx + 1
        if music:
            cmd += ["-stream_loop", "-1", "-i", str(music)]
            music_idx = idx

        fc = [f"[{i}:v]{norm}[v{i}]" for i in range(len(clips))]
        prev = "v0"
        for i, off in enumerate(offsets, 1):
            fc.append(f"[{prev}][v{i}]xfade=transition=fade:duration={a.xfade}:"
                      f"offset={off}[x{i}]")
            prev = f"x{i}"
        if end_clip:
            fc.append(f"[{end_idx}:v]{norm}[vend]")
            fc.append(f"[{prev}][vend]concat=n=2:v=1:a=0[vout]")
        else:
            fc.append(f"[{prev}]null[vout]")
        maps = ["-map", "[vout]"]
        if music:
            fade_out = max(total - 2.5, 0)
            fc.append(f"[{music_idx}:a]atrim=0:{total},asetpts=PTS-STARTPTS,"
                      f"afade=t=in:st=0:d=1.0,afade=t=out:st={fade_out:.2f}:d=2.5,"
                      f"volume={a.music_vol}[aout]")
            maps += ["-map", "[aout]", "-c:a", "aac", "-b:a", "192k"]
        else:
            maps += ["-an"]

        out = pathlib.Path(a.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        cmd += ["-filter_complex", ";".join(fc)] + maps + [
            "-t", f"{total:.3f}", "-c:v", "libx264", "-crf", "18", "-preset", "medium",
            "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(out)]
        run(cmd)

        got = probe(out)
        if abs(got["secs"] - total) > 0.5:
            out.unlink(missing_ok=True)
            print(f"ERROR: output is {got['secs']:.2f}s, expected {total:.2f}s. "
                  "Not shipping a wrong render.")
            return 1
        if not a.no_preview:
            view = out.with_name("VIEW-" + out.name)
            run([tool("ffmpeg"), "-y", "-v", "error", "-i", str(out),
                 "-vf", f"scale={608 if w < h else (960 if w > h else 720)}:-2",
                 "-c:v", "libx264",
                 "-crf", "26", "-preset", "veryfast", "-c:a", "aac", "-b:a", "128k",
                 str(view)])
    except MediaError as e:
        print(f"ERROR: {e}")
        return 1

    size_mb = out.stat().st_size / 1e6
    print(f"OK  {out}")
    print(f"    {len(clips)} beats{' + closing shot' if end_clip else ''} | "
          f"{got['secs']:.2f}s | {got['w']}x{got['h']} | {a.xfade}s crossfades | "
          f"{'music bed' if music else 'silent (add music in CapCut or any editor)'} | "
          f"{size_mb:.1f} MB")
    return 0


if __name__ == "__main__":
    sys.exit(main())
