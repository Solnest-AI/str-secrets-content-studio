#!/usr/bin/env python3
"""Crop one listing photo to the video's shape, framed on purpose.

Blind centre crops cut the wrong thing out of a room. Look at the photo, decide where
the subject sits, and pass that as --x (and --y if needed), 0.0 = left/top edge,
1.0 = right/bottom edge, 0.5 = centre. --zoom 1.15 tightens the frame a little.

Usage:
  python3 crop.py IN.jpg OUT.jpg --aspect 9:16 --x 0.42
  python3 crop.py IN.jpg OUT.jpg --aspect 16:9 --y 0.6

Always start from the largest original you have (Airbnb: ?im_w=2560).
"""
import argparse
import pathlib
import sys

from media import ASPECTS, MediaError, probe, run, tool


def crop_box(src_w, src_h, aspect, x=0.5, y=0.5, zoom=1.0):
    """Largest box of the target aspect inside the source, divided by zoom, centred on
    (x, y) as fractions and clamped to stay inside the photo. Even-numbered sizes."""
    tw, th = ASPECTS[aspect]
    target = tw / th
    if src_w / src_h > target:          # source is wider than target: height-bound
        ch = src_h
        cw = ch * target
    else:                               # source is taller/narrower: width-bound
        cw = src_w
        ch = cw / target
    cw, ch = cw / max(zoom, 1.0), ch / max(zoom, 1.0)
    cw, ch = int(cw) // 2 * 2, int(ch) // 2 * 2
    cx = min(max(int(x * src_w - cw / 2), 0), src_w - cw)
    cy = min(max(int(y * src_h - ch / 2), 0), src_h - ch)
    return cw, ch, cx, cy


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("src")
    ap.add_argument("dst")
    ap.add_argument("--aspect", default="9:16", choices=sorted(ASPECTS))
    ap.add_argument("--x", type=float, default=0.5)
    ap.add_argument("--y", type=float, default=0.5)
    ap.add_argument("--zoom", type=float, default=1.0)
    a = ap.parse_args(argv)
    try:
        info = probe(a.src)
        cw, ch, cx, cy = crop_box(info["w"], info["h"], a.aspect, a.x, a.y, a.zoom)
        tw, th = ASPECTS[a.aspect]
        pathlib.Path(a.dst).parent.mkdir(parents=True, exist_ok=True)  # crops/ on a first run
        run([tool("ffmpeg"), "-y", "-v", "error", "-i", a.src,
             "-vf", f"crop={cw}:{ch}:{cx}:{cy},scale={tw}:{th}:flags=lanczos",
             "-q:v", "2", a.dst])
    except MediaError as e:
        print(f"ERROR: {e}")
        return 1
    note = ""
    if ch < th * 0.5:
        note = "  WARNING: small source, the crop is being upscaled a lot. Use a bigger original."
    print(f"OK  {a.dst}  from {info['w']}x{info['h']} crop {cw}x{ch} at x={cx} y={cy} "
          f"-> {tw}x{th}{note}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
