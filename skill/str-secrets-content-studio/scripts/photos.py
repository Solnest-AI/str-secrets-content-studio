#!/usr/bin/env python3
"""Pull every gallery photo from an Airbnb listing page. Python stdlib only, and the
same on Mac and Windows (no curl, grep or awk).

Why the page and not a JSON scrape: measured 2026-09-25, a Firecrawl JSON scrape
returned only the 5 hero photos of a 32-photo listing. The listing page itself carries
every photo URL, so this fetches the page with a browser User-Agent, follows Airbnb's
country redirect ("Redirecting to www.airbnb.ca"), and keeps only this listing's photos.

Usage:
  <py> photos.py <airbnb url> --out source             480px thumbs of every photo -> source/thumbs/
  <py> photos.py --out source --originals 3,7,12       2560px originals of your picks -> source/
  <py> photos.py --from-urls list.txt --out source     thumbs from a URL list (Firecrawl fallback)

Airbnb's image CDN accepts ?im_w= of 480, 720, 1200 or 2560 only (400 returns a 404),
and an error page saved as .jpg looks like a photo until ffmpeg chokes on it, so every
download is checked for real image bytes.
"""
import argparse
import concurrent.futures as cf
import html as htmllib
import pathlib
import re
import sys
import time
import urllib.error
import urllib.request

for _stream in (sys.stdout, sys.stderr):      # see media.py: never crash on a non-Latin path
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36")
ROOM_ID = re.compile(r"/rooms/(?:plus/)?(\d+)")
PHOTO = re.compile(r"https://a0\.muscache\.com/im/pictures/[A-Za-z0-9/._%-]+?\.(?:jpe?g|png|webp)",
                   re.I)
REDIRECT = re.compile(r"https?://(?:www\.)?airbnb\.[a-z.]{2,10}/rooms/(?:plus/)?\d+[^\s\"'<>]*")
# Airbnb's country switch (measured 2026-09-28): a tiny page titled "Redirecting to
# www.airbnb.ca" that POSTs a form to https://www.airbnb.ca/v2/domain_switch/handoff.
# There is no link to follow, so the listing URL is rebuilt on that domain instead.
SWITCH_TITLE = re.compile(r"Redirecting to (www\.airbnb\.[a-z.]{2,10})", re.I)
SWITCH_ACTION = re.compile(r"https?://(www\.airbnb\.[a-z.]{2,10})/v2/domain_switch", re.I)
NOT_LISTING = ("/im/pictures/user/", "/im/users/", "airbnb-platform-assets", "/mediaverse/",
               "hosting-avatar", "/im/pictures/host/")
WIDTHS = (480, 720, 1200, 2560)
THUMB_W, ORIGINAL_W = 480, 2560
IMAGE_MAGIC = (b"\xff\xd8", b"\x89PNG", b"RIFF")
MIN_PHOTOS = 8


class PhotosError(RuntimeError):
    pass


def listing_id(url):
    m = ROOM_ID.search(url or "")
    return m.group(1) if m else None


def sized(url, width):
    """Airbnb CDN URL at one of the widths it actually serves. Other hosts: unchanged."""
    if "a0.muscache.com" not in url:
        return url
    if width not in WIDTHS:
        raise ValueError(f"Airbnb only serves widths {WIDTHS}, not {width}")
    return f"{url.split('?')[0]}?im_w={width}"


def with_locale(url):
    if "locale=" in url:
        return url
    return url + ("&" if "?" in url else "?") + "locale=en"


def extract_photo_urls(page, lid=None):
    """Every listing photo URL on the page, in page order, deduped, query stripped.
    Returns (urls, own): own is True when the list could be narrowed to this listing's
    Hosting-<id> photos (newer listings). False means it could not (older listings), so
    the page's 'similar listings' pictures may be mixed in: look at the sheet with care."""
    text = htmllib.unescape(page.replace("\\u002F", "/").replace("\\/", "/"))
    urls, seen = [], set()
    for m in PHOTO.finditer(text):
        u = m.group(0)
        if u in seen or any(s in u for s in NOT_LISTING):
            continue
        seen.add(u)
        urls.append(u)
    if lid:
        own = [u for u in urls if f"Hosting-{lid}/" in u]
        if own:
            return own, True
    return urls, False


def fetch(url, timeout=45):
    req = urllib.request.Request(url, headers={
        "User-Agent": UA, "Accept": "text/html,application/xhtml+xml,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.geturl(), r.read().decode("utf-8", "replace")


def redirect_target(body, lid):
    """The listing URL to fetch next when `body` is one of Airbnb's country-redirect
    pages (a POST form to the local domain, or a plain meta refresh), else None."""
    if len(body) > 20000:
        return None
    m = SWITCH_TITLE.search(body) or SWITCH_ACTION.search(body)
    if m and lid:
        return f"https://{m.group(1)}/rooms/{lid}"
    m = REDIRECT.search(body)
    return m.group(0) if m else None


def fetch_listing(url, lid=None):
    """Fetch the page, following Airbnb's tiny country-redirect page if it serves one."""
    lid = lid or listing_id(url)
    tried = []
    for _ in range(4):
        tried.append(url.split("?")[0])
        final, body = fetch(url)
        nxt = redirect_target(body, lid)
        if nxt is None:
            return final, body
        if nxt.split("?")[0] in tried:
            break
        url = with_locale(nxt)
    raise PhotosError("Airbnb kept redirecting between country sites: " + " -> ".join(tried))


def download(url, dest, retries=3):
    last = None
    for attempt in range(1, retries + 1):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA,
                                                       "Accept": "image/*,*/*;q=0.8"})
            with urllib.request.urlopen(req, timeout=60) as r:
                data = r.read()
            if len(data) > 1000 and data.startswith(IMAGE_MAGIC):
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_bytes(data)
                return len(data)
            last = PhotosError(f"not an image ({len(data)} bytes)")
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            last = e
        time.sleep(1.5 * attempt)
    raise PhotosError(f"{dest.name}: {last}")


def ext_of(url):
    e = url.split("?")[0].rsplit(".", 1)[-1].lower()
    return ".jpg" if e in ("jpg", "jpeg") else f".{e}"


def numbered(i, n):
    return f"{i:0{max(2, len(str(n)))}d}"


def run_downloads(jobs, workers):
    """jobs: {number: (url, dest)}. Returns (ok numbers, {number: error})."""
    ok, bad = [], {}

    def one(item):
        i, (url, dest) = item
        try:
            return i, download(url, dest), None
        except PhotosError as e:
            return i, 0, str(e)

    with cf.ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        for i, size, err in pool.map(one, sorted(jobs.items())):
            if err:
                bad[i] = err
            else:
                ok.append(i)
    return ok, bad


def read_urls(path):
    return [line.strip() for line in pathlib.Path(path).read_text(encoding="utf-8").splitlines()
            if line.strip() and not line.startswith("#")]


def clear_numbered(folder):
    """Remove NN.jpg-style files from an earlier pull so a rerun (or a different listing
    under the same slug) can never leave old photos next to the new ones."""
    folder = pathlib.Path(folder)
    if not folder.is_dir():
        return 0
    gone = 0
    for p in folder.iterdir():
        if p.is_file() and p.stem.isdigit() and p.suffix.lower() in (".jpg", ".jpeg", ".png", ".webp"):
            p.unlink()
            gone += 1
    return gone


def save_thumbs(urls, out, workers):
    n = len(urls)
    clear_numbered(out / "thumbs")
    clear_numbered(out)
    print(f"downloading {n} thumbnails ({THUMB_W}px) to {out / 'thumbs'} ...", flush=True)
    jobs = {i: (sized(u, THUMB_W), out / "thumbs" / f"{numbered(i, n)}{ext_of(u)}")
            for i, u in enumerate(urls, 1)}
    ok, bad = run_downloads(jobs, workers)
    print(f"  {len(ok)} saved" + (f", {len(bad)} failed: " + ", ".join(
        f"{i}: {e}" for i, e in bad.items()) if bad else ""))
    print(f"  photo numbers 1..{n} match the file names in {out / 'thumbs'}")
    print(f"next: sheet.py {out / '_sheet.jpg'} {out / 'thumbs'} --cols 5, then look at it")
    return 0 if not bad else 1


def fetch_gallery(url, out, workers):
    if "airbnb." not in url.lower():
        raise PhotosError("not an Airbnb link. For VRBO, Zillow and other sites use the "
                          "Firecrawl fallback in SKILL.md step 1, then --from-urls.")
    lid = listing_id(url)
    if not lid:
        raise PhotosError("no listing id in that link; use the "
                          "https://www.airbnb.com/rooms/<id> form")
    try:
        final, page = fetch_listing(with_locale(url), lid)
    except urllib.error.HTTPError as e:
        raise PhotosError(f"Airbnb answered HTTP {e.code}. Try again in a minute, or use the "
                          "Firecrawl fallback in SKILL.md step 1.")
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        raise PhotosError(f"could not reach Airbnb ({e}). Check the internet connection.")
    out.mkdir(parents=True, exist_ok=True)
    (out / "_page.html").write_text(page, encoding="utf-8")
    urls, own = extract_photo_urls(page, lid)
    if not urls:
        raise PhotosError(f"no photos found on the page (saved to {out / '_page.html'}). "
                          "Use the Firecrawl fallback in SKILL.md step 1.")
    with open(out / "_urls.txt", "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(urls) + "\n")
    print(f"listing {lid}: {len(urls)} photos found on {final.split('?')[0]}")
    if not own:
        print("  note: could not tell this listing's photos apart from the page's "
              "similar-listings pictures; check the sheet with care")
    if len(urls) < MIN_PHOTOS:
        print(f"  only {len(urls)} photos: if the sheet looks thin, use the Firecrawl "
              "fallback in SKILL.md step 1")
    return save_thumbs(urls, out, workers)


def fetch_originals(out, spec, workers):
    urls = read_urls(out / "_urls.txt")
    n = len(urls)
    picks = []
    for s in spec.split(","):
        s = s.strip()
        if not s:
            continue
        if not s.isdigit() or not 1 <= int(s) <= n:
            raise PhotosError(f"--originals: {s!r} is not a photo number between 1 and {n}")
        picks.append(int(s))
    jobs = {i: (sized(urls[i - 1], ORIGINAL_W), out / f"{numbered(i, n)}{ext_of(urls[i - 1])}")
            for i in picks}
    print(f"downloading {len(picks)} originals ({ORIGINAL_W}px) to {out} ...", flush=True)
    ok, bad = run_downloads(jobs, workers)
    for i in sorted(ok):
        dest = jobs[i][1]
        print(f"  OK  {dest}  ({dest.stat().st_size / 1e6:.1f} MB)")
    for i, e in bad.items():
        print(f"  FAIL  photo {i}: {e}")
    return 0 if not bad else 1


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("url", nargs="?", help="Airbnb listing link")
    ap.add_argument("--out", default="source", help="folder for the photos (default: source)")
    ap.add_argument("--originals", default="",
                    help="comma list of photo numbers to fetch at 2560px (after you chose)")
    ap.add_argument("--from-urls", default="",
                    help="text file with one photo URL per line, for non-Airbnb listings")
    ap.add_argument("--workers", type=int, default=8)
    a = ap.parse_args(argv)
    out = pathlib.Path(a.out)
    try:
        if a.originals:
            return fetch_originals(out, a.originals, a.workers)
        if a.from_urls:
            urls = read_urls(a.from_urls)
            if not urls:
                raise PhotosError(f"{a.from_urls} has no URLs in it")
            out.mkdir(parents=True, exist_ok=True)
            with open(out / "_urls.txt", "w", encoding="utf-8", newline="\n") as f:
                f.write("\n".join(urls) + "\n")
            return save_thumbs(urls, out, a.workers)
        if not a.url:
            ap.error("give an Airbnb listing link, or --originals 3,7,12, or --from-urls FILE")
        return fetch_gallery(a.url, out, a.workers)
    except PhotosError as e:
        print(f"ERROR: {e}")
        return 2


if __name__ == "__main__":
    sys.exit(main())
