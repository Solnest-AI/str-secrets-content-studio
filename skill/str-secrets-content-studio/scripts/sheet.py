#!/usr/bin/env python3
"""Contact sheet: many photos (or one frame from each video clip) in one image, so you
can see every room at once.

Scraped room labels are unreliable (on one test listing EVERY label was wrong). Look
at the pictures. Tiles are laid out left to right, top to bottom, in the order given;
the script prints the tile number for each file.

Usage:
  <py> sheet.py OUT.jpg source/thumbs --cols 5        every image in a folder, sorted
  <py> sheet.py OUT.jpg clips --tile 360              one frame from each clip (--at seconds in)
  <py> sheet.py OUT.jpg a.jpg b.jpg "c/*.jpg"         files and globs (expanded here, so they
                                                      work from PowerShell too)

In folder mode, files starting with _ (sheets, check frames, the ending seed) are skipped.
"""
import argparse
import glob
import pathlib
import sys

from media import MediaError, probe, run, tool

IMAGE_EXT = {".jpg", ".jpeg", ".png", ".webp"}
VIDEO_EXT = {".mp4", ".mov", ".m4v", ".webm", ".mkv"}
MAX_TILES = 100


def expand_inputs(items):
    """Files as given; globs expanded; folders listed (images and videos, sorted)."""
    out = []
    for it in items:
        p = pathlib.Path(it)
        if any(ch in it for ch in "*?["):
            out += sorted(pathlib.Path(x) for x in glob.glob(it))
        elif p.is_dir():
            out += sorted(x for x in p.iterdir()
                          if x.suffix.lower() in IMAGE_EXT | VIDEO_EXT
                          and not x.name.startswith("_"))
        else:
            out.append(p)
    return out


def frame_of(video, at, out_dir):
    """One frame from a clip, `at` seconds in (or its middle if the clip is shorter)."""
    secs = probe(video)["secs"]
    t = min(at, secs / 2) if secs else 0.0
    dest = out_dir / f"_check_{video.stem}.jpg"
    run([tool("ffmpeg"), "-y", "-v", "error", "-ss", f"{t:.2f}", "-i", str(video),
         "-frames:v", "1", "-q:v", "3", str(dest)])
    return dest


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("out")
    ap.add_argument("inputs", nargs="+", help="image or video files, folders, or globs")
    ap.add_argument("--cols", type=int, default=4)
    ap.add_argument("--tile", type=int, default=480, help="tile width in pixels")
    ap.add_argument("--at", type=float, default=3.0, help="seconds into each video clip")
    a = ap.parse_args(argv)

    out = pathlib.Path(a.out)
    files = expand_inputs(a.inputs)
    if not files:
        print(f"ERROR: no images or videos found in {a.inputs}")
        return 1
    if len(files) > MAX_TILES:
        print(f"note: {len(files)} files, showing the first {MAX_TILES}")
        files = files[:MAX_TILES]
    try:
        out.parent.mkdir(parents=True, exist_ok=True)
        tiles = [frame_of(f, a.at, out.parent) if f.suffix.lower() in VIDEO_EXT else f
                 for f in files]
        n = len(tiles)
        cols = max(1, min(a.cols, n))
        # tile shape follows the first picture: 9:16 crops and clips get tall tiles,
        # listing photos get wide ones, so nothing is shrunk into a letterbox
        first = probe(tiles[0])
        tw = a.tile // 2 * 2
        th = (a.tile * 16 // 9 if first["h"] > first["w"] else a.tile * 2 // 3) // 2 * 2
        # even sizes only: an odd tile height (400 x 711) made ffmpeg die without a message
        cmd = [tool("ffmpeg"), "-y", "-v", "error"]
        for p in tiles:
            cmd += ["-i", str(p)]
        # fit = the one factor that keeps the picture inside the tile. Written out like
        # this because scale=W:H:force_original_aspect_ratio=decrease can round UP by a
        # pixel (711.1 -> 712), and pad then refuses with "Padded dimensions cannot be
        # smaller than input dimensions" (hit on the first real Windows run, 2026-09-28).
        fit = f"min({tw}/iw\\,{th}/ih)"
        parts = []
        for i in range(n):
            parts.append(f"[{i}:v]scale=iw*{fit}:ih*{fit},"
                         f"pad={tw}:{th}:(ow-iw)/2:(oh-ih)/2:color=black,setsar=1[t{i}]")
        if n == 1:
            graph = parts[0].replace("[t0]", "[out]")
        else:
            layout = "|".join(f"{(i % cols) * tw}_{(i // cols) * th}" for i in range(n))
            inputs = "".join(f"[t{i}]" for i in range(n))
            graph = (";".join(parts)
                     + f";{inputs}xstack=inputs={n}:layout={layout}:fill=black[out]")
        cmd += ["-filter_complex", graph, "-map", "[out]", "-frames:v", "1", "-q:v", "3",
                str(out)]
        run(cmd)
    except MediaError as e:
        print(f"ERROR: {e}")
        return 1
    print(f"OK  {out}  ({n} tiles, {cols} per row)")
    for i, p in enumerate(files, 1):
        print(f"  tile {i:2d}: {p}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
