#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# dependencies = ["playwright==1.60.0", "pillow>=10"]
# ///
"""Pull everything a carousel needs from a listing: every photo at full size, the listing
text (the only source of truth for claims), and the guest reviews. No API key.

It opens the page in a headless browser (Playwright), because Airbnb only renders review
text in the browser: a plain fetch of the page has the photos and description but no
reviews (measured 2026-09-26). The same render also follows Airbnb's country redirect.

Writes, under OUTDIR/source/:
  full/NN.jpg     every photo, largest size Airbnb serves (2560 wide)
  thumbs/NN.jpg   480px copies
  _sheet.jpg      numbered contact sheet: LOOK at this before planning
  facts.txt       title, overview, highlights, description, amenities, location, policies
  reviews.json    [{author, location, when, rating, text}] (empty if none)
  listing.json    url, id, counts

Usage:
  python3 listing_pull.py https://www.airbnb.com/rooms/123 listing-carousels/lake-house
  python3 listing_pull.py --folder ~/Photos/LakeHouse listing-carousels/lake-house [--facts desc.txt]

Exit 0 = ready, 2 = could not get enough (the message says what to do instead).
Needs: pip install playwright pillow ; python -m playwright install chromium
"""
import argparse
import concurrent.futures as cf
import io
import json
import pathlib
import re
import shutil
import sys
import time
import urllib.request

from PIL import Image, ImageDraw, ImageFont, ImageOps

import browser

SKILL_DIR = pathlib.Path(__file__).resolve().parent.parent
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36")
MIN_PHOTOS = 8
FACT_SECTIONS = [("TITLE_DEFAULT", "TITLE"), ("OVERVIEW_DEFAULT_V2", "OVERVIEW"),
                 ("HIGHLIGHTS_DEFAULT", "HIGHLIGHTS"), ("DESCRIPTION_DEFAULT", "DESCRIPTION"),
                 ("SLEEPING_ARRANGEMENT_DEFAULT", "SLEEPING"), ("AMENITIES_DEFAULT", "AMENITIES (preview)"),
                 ("LOCATION_DEFAULT", "LOCATION"), ("POLICIES_DEFAULT", "POLICIES")]
FOLDER_FIX = ("Instead: save the listing photos into one folder, paste the listing description "
              "into a text file, and run:  listing_pull.py --folder <photos> <out> --facts <description.txt>")


def out(msg):
    print(str(msg).encode("ascii", "replace").decode("ascii"), flush=True)


# --- parsing (pure, tested) -----------------------------------------------------

RATING = re.compile(r"Rating,\s*(\d+(?:\.\d+)?)\s*stars?", re.I)
NOT_PLACE = re.compile(r"on Airbnb|hosting|^Rating", re.I)
WHEN = re.compile(r"\bago\b|\b(19|20)\d{2}\b", re.I)
TRIP = re.compile(r"^(stayed\b.{0,40}|.{0,30}\btrip)$", re.I)
SKIP = ("show more", "translated from", "show original", "show translation", "read more")


def parse_reviews(items):
    """innerText of each review card -> [{author, location, when, rating, text}]."""
    reviews = []
    for raw in items:
        lines = [l.strip() for l in str(raw or "").split("\n")]
        lines = [l for l in lines if l and l not in {",", "·"}]
        ri = next((i for i, l in enumerate(lines) if RATING.search(l)), None)
        if ri is None or ri < 1:
            continue
        loc = lines[1] if ri >= 2 else None
        if loc and NOT_PLACE.search(loc):
            loc = None
        rest = lines[ri + 1:]
        when = rest.pop(0) if rest and len(rest[0]) <= 30 and WHEN.search(rest[0]) else None
        if len(rest) > 1 and TRIP.match(rest[0]):
            rest.pop(0)
        body = []
        for l in rest:
            low = l.lower()
            if low.startswith("response from"):
                break
            if low.startswith(SKIP):
                continue
            body.append(l)
        text = "\n".join(body).strip()
        if not text:
            continue
        rating = float(RATING.search(lines[ri]).group(1))
        reviews.append({"author": lines[0], "location": loc, "when": when,
                        "rating": int(rating) if rating.is_integer() else rating, "text": text})
    return reviews


def photo_urls(html, listing_id):
    pat = re.compile(r"https://a0\.muscache\.com/im/pictures/[A-Za-z0-9/_-]*Hosting-" + re.escape(str(listing_id))
                     + r"/original/[A-Za-z0-9-]+\.(?:jpeg|jpg|png|webp)")
    return list(dict.fromkeys(pat.findall(html)))


def amenity_titles(html):
    """Available amenities from the page's full amenity list (the page shows only ~10)."""
    i = html.find('"seeAllAmenitiesGroups"')
    if i < 0:
        return []
    j = html.find("[", i)
    try:
        groups, _ = json.JSONDecoder().raw_decode(html, j)
    except ValueError:
        return []
    if not isinstance(groups, list):
        return []
    titles = [a["title"] for g in groups if isinstance(g, dict) for a in (g.get("amenities") or [])
              if isinstance(a, dict) and a.get("available") and a.get("title")]
    return list(dict.fromkeys(titles))


# --- browser --------------------------------------------------------------------

PAGE_JS = """() => {
  const sections = {};
  document.querySelectorAll('[data-section-id]').forEach(e => { sections[e.getAttribute('data-section-id')] = e.innerText; });
  const rs = document.querySelector('[data-section-id="REVIEWS_DEFAULT"]') || document.querySelector('[data-section-id*="REVIEWS"]');
  let cards = rs ? [...rs.querySelectorAll('[data-review-id]')] : [];
  if (rs && !cards.length) cards = [...rs.querySelectorAll('div[role="listitem"]')];
  const images = [...document.images].filter(i => i.naturalWidth >= 900).map(i => i.currentSrc || i.src);
  const main = document.querySelector('main');
  return {sections, reviews: cards.map(c => c.innerText), images, body: (main || document.body).innerText};
}"""


def render_page(url):
    from playwright.sync_api import sync_playwright
    with sync_playwright() as pw:
        br = browser.launch(pw)
        try:
            pg = br.new_page(user_agent=UA, viewport={"width": 1280, "height": 900}, locale="en-US")
            pg.goto(url, wait_until="domcontentloaded", timeout=60000)
            try:
                pg.wait_for_selector('[data-section-id="DESCRIPTION_DEFAULT"], main img', timeout=20000)
            except Exception:
                pass
            for _ in range(14):  # reviews and lazy images load on scroll
                pg.mouse.wheel(0, 1400)
                pg.wait_for_timeout(400)
            try:
                pg.wait_for_selector('[data-section-id*="REVIEWS"] [data-review-id], '
                                     '[data-section-id*="REVIEWS"] div[role="listitem"]', timeout=6000)
            except Exception:
                pass
            data = pg.evaluate(PAGE_JS)
            data.update(html=pg.content(), url=pg.url)
            return data
        finally:
            br.close()


# --- files ----------------------------------------------------------------------

def fetch(url, dest, tries=3):
    last = None
    for k in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=60) as r:
                data = r.read()
            if len(data) < 10000:
                raise ValueError(f"only {len(data)} bytes")
            im = Image.open(io.BytesIO(data))
            im.load()  # decode fully BEFORE anything touches the disk
            if im.format == "JPEG":
                dest.write_bytes(data)
            else:
                im.convert("RGB").save(dest, "JPEG", quality=95)
            return True
        except Exception as e:  # network, 404, an HTML error page, a truncated image
            last = e
            time.sleep(1.5 * (k + 1))
    if dest.exists():
        dest.unlink()
    out(f"  could not download {url}: {last}")
    return False


def label_font(size):
    try:
        return ImageFont.truetype(str(SKILL_DIR / "fonts" / "Inter.ttf"), size)
    except OSError:
        return ImageFont.load_default()


def make_thumbs_and_sheet(src):
    full = sorted((src / "full").glob("*.jpg"))
    (src / "thumbs").mkdir(exist_ok=True)
    tw, th, cols = 320, 240, 6
    rows = (len(full) + cols - 1) // cols
    sheet = Image.new("RGB", (cols * tw, rows * th), "black")
    d = ImageDraw.Draw(sheet)
    f = label_font(26)
    for i, p in enumerate(full):
        try:
            im = Image.open(p)
            im.thumbnail((480, 480))
        except Exception as e:  # never let one bad file sink the whole pull
            out(f"  skipping unreadable photo {p.name}: {e}")
            continue
        im.save(src / "thumbs" / p.name, quality=85)
        t = im.copy()
        t.thumbnail((tw - 4, th - 4))
        x, y = (i % cols) * tw, (i // cols) * th
        sheet.paste(t, (x + (tw - t.width) // 2, y + (th - t.height) // 2))
        d.rectangle([x + 4, y + 4, x + 54, y + 38], fill="white")
        d.text((x + 10, y + 6), p.stem, fill="black", font=f)
    sheet.save(src / "_sheet.jpg", quality=88)


def write_json(path, obj):
    path.write_text(json.dumps(obj, indent=1, ensure_ascii=False), encoding="utf-8")


# --- pulls ----------------------------------------------------------------------

def pull_url(url, outdir, render=render_page, minimum=MIN_PHOTOS):
    src = pathlib.Path(outdir) / "source"
    m = re.search(r"airbnb\.[a-z.]+/rooms/(?:plus/)?(\d+)", url)
    lid = m.group(1) if m else None
    if lid:
        url = f"https://www.airbnb.com/rooms/{lid}?locale=en"
    out(f"Opening {url} ...")
    try:
        page = render(url)
    except Exception as e:
        out(f"ERROR: could not open the listing ({e}).\n{FOLDER_FIX}")
        return 2
    html, sections = page.get("html", ""), page.get("sections") or {}
    urls = photo_urls(html, lid) if lid else list(dict.fromkeys(page.get("images") or []))
    if len(urls) < minimum:
        out(f"ERROR: found only {len(urls)} listing photos (need {minimum}). The site blocked the "
            f"browser or changed its layout.\n{FOLDER_FIX}")
        return 2

    (src / "full").mkdir(parents=True, exist_ok=True)
    jobs = [(u + ("?im_w=2560" if lid else ""), src / "full" / f"{i:02d}.jpg") for i, u in enumerate(urls, 1)]
    with cf.ThreadPoolExecutor(max_workers=6) as ex:
        got = list(ex.map(lambda j: fetch(*j), jobs))
    missing = [j[1].stem for j, ok in zip(jobs, got) if not ok]
    if sum(got) < minimum:
        out(f"ERROR: only {sum(got)} photos downloaded.\n{FOLDER_FIX}")
        return 2
    make_thumbs_and_sheet(src)
    (src / "_urls.txt").write_text("\n".join(urls) + "\n", encoding="utf-8")

    parts = [f"SOURCE: {page.get('url', url)} (public listing page, rendered {time.strftime('%Y-%m-%d')})"]
    for key, name in FACT_SECTIONS:
        if sections.get(key):
            parts.append(f"== {name} ==\n{sections[key].strip()}")
    am = amenity_titles(html)
    if am:
        parts.append("== AMENITIES (full list, available only) ==\n" + "\n".join(am))
    if not lid and page.get("body"):
        parts.append("== PAGE TEXT ==\n" + page["body"].strip())
    (src / "facts.txt").write_text("\n\n".join(parts) + "\n", encoding="utf-8")

    reviews = parse_reviews(page.get("reviews") or [])
    write_json(src / "reviews.json", reviews)
    five = sum(1 for r in reviews if r["rating"] == 5)
    write_json(src / "listing.json", {"url": page.get("url", url), "listing_id": lid, "photos": sum(got),
                                      "missing_photos": missing, "reviews": len(reviews), "five_star": five})
    out(f"OK  {sum(got)} photos, {len(reviews)} reviews ({five} five-star), "
        f"{len(parts) - 1} text sections, {len(am)} amenities -> {src}")
    if missing:
        out(f"note: photos {missing} failed to download and are skipped")
    if not sections.get("DESCRIPTION_DEFAULT") and lid:
        out("note: no description found; only the overview and amenities can back claims")
    out(f"Now LOOK at {src / '_sheet.jpg'} before planning any slide.")
    return 0


PHOTO_EXT = {".jpg", ".jpeg", ".png", ".webp"}


def pull_folder(folder, outdir, facts_file=None, minimum=5):
    folder, src = pathlib.Path(folder).expanduser(), pathlib.Path(outdir) / "source"
    files = sorted((p for p in folder.iterdir() if p.suffix.lower() in PHOTO_EXT), key=lambda p: p.name.lower())
    heic = [p.name for p in folder.iterdir() if p.suffix.lower() in (".heic", ".heif")]
    if heic:
        out(f"note: skipped {len(heic)} HEIC photos; export them as JPEG first")
    if len(files) < minimum:
        out(f"ERROR: {len(files)} usable photos in {folder} (need at least {minimum}, JPG/PNG/WEBP).")
        return 2
    (src / "full").mkdir(parents=True, exist_ok=True)
    for i, p in enumerate(files, 1):
        ImageOps.exif_transpose(Image.open(p)).convert("RGB").save(src / "full" / f"{i:02d}.jpg", quality=95)
    make_thumbs_and_sheet(src)
    head = "SOURCE: host-supplied photos"
    if facts_file:
        text = pathlib.Path(facts_file).expanduser().read_text(encoding="utf-8")
        (src / "facts.txt").write_text(f"{head}; listing text from {facts_file}\n\n{text}\n", encoding="utf-8")
    else:
        (src / "facts.txt").write_text(f"{head}; NO listing text yet. Add the host's own description "
                                       "here before claiming anything on a slide.\n", encoding="utf-8")
    write_json(src / "reviews.json", [])
    write_json(src / "listing.json", {"folder": str(folder), "photos": len(files), "reviews": 0})
    out(f"OK  {len(files)} photos -> {src}. Now LOOK at {src / '_sheet.jpg'}.")
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("args", nargs="+", help="URL OUTDIR, or with --folder just OUTDIR")
    ap.add_argument("--folder", help="use a folder of photos instead of a URL")
    ap.add_argument("--facts", help="text file with the listing description (folder mode)")
    a = ap.parse_args(argv)
    if a.folder:
        return pull_folder(a.folder, a.args[-1], a.facts)
    if len(a.args) != 2:
        ap.error("give a listing URL and an output folder")
    return pull_url(a.args[0], a.args[1])


if __name__ == "__main__":
    sys.exit(main())
