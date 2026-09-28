#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# dependencies = ["playwright==1.60.0", "pillow>=10"]
# ///
"""Read a host's brand from their own website: colours by how much of the page they paint,
the fonts on headings and body text, and every plausible logo, each cut out onto a
transparent background. No API key; a headless browser (Playwright) does the reading.

Claude then LOOKS at site.png and the logo candidates and writes brand/brand.json (see
CAROUSEL.md). This script never decides the brand on its own: sites are messy, and a
cookie banner or a hero photo can outvote the real palette.

Writes, under OUTDIR/:
  site.png                 the top of the homepage, as a visitor sees it
  brand_raw.json           colours, fonts, site name, logo candidates
  logo_candidates/NN.png   each candidate with a transparent background

Usage:
  python3 brand_pull.py https://www.lakeviewcabins.com listing-carousels/lake-house/brand
Exit 0 = pulled (even with no logo), 2 = the site would not load.
"""
import argparse
import json
import pathlib
import re
import sys

from PIL import Image, ImageChops, ImageOps

import browser

UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36")


def out(msg):
    print(str(msg).encode("ascii", "replace").decode("ascii"), flush=True)


# --- pure helpers (tested) ------------------------------------------------------

def css_hex(css):
    """'rgb(1, 2, 3)' / 'rgba(1, 2, 3, 0.5)' -> '#010203'; None if (nearly) transparent."""
    m = re.match(r"rgba?\(\s*(\d+)[,\s]+(\d+)[,\s]+(\d+)(?:[,\s/]+([\d.]+))?", str(css or ""))
    if not m:
        return None
    if m.group(4) is not None and float(m.group(4)) < 0.5:
        return None
    return "#" + "".join(f"{int(m.group(i)):02X}" for i in (1, 2, 3))


def palette(counts, top=8):
    """[(hex, weight)] -> [(hex, share)] with near-duplicates merged, biggest first."""
    merged = []
    for h, w in sorted(counts, key=lambda c: -c[1]):
        rgb = tuple(int(h[i:i + 2], 16) for i in (1, 3, 5))
        for m in merged:
            if sum(abs(a - b) for a, b in zip(rgb, m["rgb"])) < 18:
                m["w"] += w
                break
        else:
            merged.append({"hex": h.upper(), "rgb": rgb, "w": w})
    total = sum(m["w"] for m in merged) or 1
    merged.sort(key=lambda m: -m["w"])
    return [(m["hex"], round(m["w"] / total, 3)) for m in merged[:top]]


_BOOKING = re.compile(r"\b(book|reserve|availability|check dates|stay with us|enquire|inquire)\b", re.I)


def suggest_cta(candidates, domain):
    """A starting call to action from the site's own booking button: "Book Your Stay" on
    lakeviewcabins.com becomes "Book your stay at lakeviewcabins.com". None if the site has no
    booking button; the host always gets the final word."""
    dom = re.sub(r"^www\.", "", (domain or "").strip().lower())
    for c in candidates or []:
        text = re.sub(r"\s+", " ", str(c.get("text", ""))).strip()
        if 3 <= len(text) <= 40 and _BOOKING.search(text):
            line = text[0].upper() + text[1:].lower()
            return f"{line} at {dom}" if dom else line
    return None


def to_alpha(img):
    """A logo with a transparent background, cropped to the mark, or None.
    Keeps real transparency; otherwise keys out a plain light or dark box by luminance.
    Refuses mid-tone boxes (usually a photo, not a logo) and blank images."""
    im = img.convert("RGBA")
    a = im.split()[3]
    if a.getextrema()[0] < 250:  # real transparency
        box = a.point(lambda v: 255 if v > 8 else 0).getbbox()
        return im.crop(box) if box else None
    g = ImageOps.grayscale(im.convert("RGB"))
    w, h = g.size
    edge = [g.getpixel((x, y)) for x in range(0, w, max(1, w // 40)) for y in (0, h - 1)]
    edge += [g.getpixel((x, y)) for y in range(0, h, max(1, h // 20)) for x in (0, w - 1)]
    edge.sort()
    bg = edge[len(edge) // 2]
    if bg >= 200:
        key = ImageChops.invert(g)          # dark mark on a light box
        span = max(1, bg - min(g.getextrema()[0], bg - 1))
        base = 255 - bg
    elif bg <= 55:
        key, span, base = g, max(1, max(g.getextrema()[1], bg + 1) - bg), bg
    else:
        return None
    alpha = key.point(lambda v: max(0, min(255, int((v - base) * 255 / span))))
    alpha = alpha.point(lambda v: 0 if v < 24 else v)
    box = alpha.getbbox()
    if not box:
        return None
    im.putalpha(alpha)
    return im.crop(box)


# --- browser --------------------------------------------------------------------

READ_JS = """() => {
  const bg = {}, fg = {}, btn = {};
  const add = (o, k, w) => { if (k) o[k] = (o[k] || 0) + w; };
  const els = [...document.querySelectorAll('body, body *')].slice(0, 4000);
  for (const el of els) {
    const r = el.getBoundingClientRect();
    if (r.width < 2 || r.height < 2 || r.bottom < 0 || r.top > 6000) continue;
    const cs = getComputedStyle(el);
    if (cs.visibility === 'hidden' || cs.display === 'none' || +cs.opacity < 0.5) continue;
    add(bg, cs.backgroundColor, Math.min(r.width, 1280) * Math.min(r.height, 1200));
    const own = [...el.childNodes].filter(n => n.nodeType === 3).map(n => n.textContent.trim()).join('');
    if (own.length) add(fg, cs.color, own.length * parseFloat(cs.fontSize));
    if (el.matches('button, a[class*="button" i], [role="button"], .btn')) add(btn, cs.backgroundColor, r.width * r.height);
  }
  const font = sel => { const e = document.querySelector(sel); return e ? getComputedStyle(e).fontFamily : null; };
  const meta = n => (document.querySelector(`meta[property="${n}"], meta[name="${n}"]`) || {}).content || null;
  const ctas = [...document.querySelectorAll('a, button')].filter(e => { const r = e.getBoundingClientRect();
      return r.width > 0 && r.height > 0; }).map(e => ({text: (e.innerText || '').trim(), href: e.getAttribute('href') || ''}))
    .filter(c => c.text && c.text.length <= 40).slice(0, 60);
  return {bg: Object.entries(bg), fg: Object.entries(fg), btn: Object.entries(btn),
          fonts: {h1: font('h1'), h2: font('h2'), h3: font('h3'), body: font('p') || font('body'), button: font('button, a[class*="button" i]')},
          site_name: meta('og:site_name'), title: document.title, url: location.href, host: location.hostname,
          ctas};
}"""

LOGO_SEL = ("header img, header svg, [class*='logo' i] img, [class*='logo' i] svg, img[class*='logo' i], "
            "img[alt*='logo' i], img[src*='logo' i], [id*='logo' i] img, [id*='logo' i] svg, "
            "a[href='/'] img, a[href='/'] svg")


def read_site(url, outdir):
    from playwright.sync_api import sync_playwright
    cand = outdir / "logo_candidates"
    cand.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as pw:
        br = browser.launch(pw)
        try:
            pg = br.new_page(user_agent=UA, viewport={"width": 1280, "height": 900}, device_scale_factor=3)
            pg.goto(url, wait_until="domcontentloaded", timeout=60000)
            try:
                pg.wait_for_load_state("networkidle", timeout=15000)
            except Exception:
                pass
            pg.wait_for_timeout(1500)
            pg.screenshot(path=str(outdir / "site.png"))
            data = pg.evaluate(READ_JS)
            logos, seen = [], set()
            for el in pg.query_selector_all(LOGO_SEL)[:20]:
                try:
                    box = el.bounding_box()
                    if not box or box["width"] < 30 or box["height"] < 14 or box["width"] > 700 or box["y"] > 1500:
                        continue
                    key = el.get_attribute("src") or f"{round(box['x'])},{round(box['y'])}"
                    if key in seen:
                        continue
                    seen.add(key)
                    raw = cand / f"_raw{len(seen):02d}.png"
                    el.screenshot(path=str(raw), omit_background=True)
                    cut = to_alpha(Image.open(raw))
                    raw.unlink()
                    if cut is None or cut.width < 40:
                        continue
                    n = len(logos) + 1
                    cut.save(cand / f"{n:02d}.png")
                    logos.append({"file": f"logo_candidates/{n:02d}.png", "from": key[:200],
                                  "size": [cut.width, cut.height], "top_px": round(box["y"])})
                except Exception:
                    continue
            data["logo_candidates"] = logos
            return data
        finally:
            br.close()


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("url")
    ap.add_argument("outdir")
    a = ap.parse_args(argv)
    url = a.url if a.url.startswith("http") else "https://" + a.url
    outdir = pathlib.Path(a.outdir)
    outdir.mkdir(parents=True, exist_ok=True)
    try:
        d = read_site(url, outdir)
    except Exception as e:
        out(f"ERROR: could not load {url}: {e}")
        return 2
    raw = {"url": d["url"], "site_name": d.get("site_name"), "title": d.get("title"), "fonts": d["fonts"],
           "backgrounds": palette([(h, w) for c, w in d["bg"] if (h := css_hex(c))]),
           "text_colors": palette([(h, w) for c, w in d["fg"] if (h := css_hex(c))]),
           "button_colors": palette([(h, w) for c, w in d["btn"] if (h := css_hex(c))], top=4),
           "logo_candidates": d["logo_candidates"],
           "cta_candidates": [c for c in d.get("ctas", []) if _BOOKING.search(c["text"])][:5],
           "suggested_cta": suggest_cta(d.get("ctas", []), d.get("host", ""))}
    (outdir / "brand_raw.json").write_text(json.dumps(raw, indent=1, ensure_ascii=False), encoding="utf-8")
    out(f"OK  {raw['site_name'] or raw['title']}: {len(raw['backgrounds'])} background colours, "
        f"{len(raw['logo_candidates'])} logo candidates -> {outdir}")
    out(f"  backgrounds: {raw['backgrounds'][:5]}")
    out(f"  text:        {raw['text_colors'][:4]}")
    out(f"  buttons:     {raw['button_colors']}")
    out(f"  fonts:       {raw['fonts']}")
    out(f"  suggested call to action: {raw['suggested_cta'] or '(none found: ask the host for their line)'}")
    out(f"Now LOOK at {outdir / 'site.png'} and each logo candidate, then write brand.json.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
