#!/usr/bin/env python3
"""Ad Spy: find the ads competitors are running on Facebook and Instagram, with their full
copy, images and videos, ranked by how hard they are spending. Python stdlib only.

It reads Meta's public Ad Library page through Firecrawl (the host's FIRECRAWL_API_KEY from
the STR Secrets Connections kit). Measured 2026-09-28 on "short term rental management
Nashville" against Meta's own Ad Library search: same advertisers, but Meta's search
returns headlines only, while the page carries every ad's body copy, call to action, landing
link, image and video files, start date, and how many copies of the creative are running.
The page is also sorted by impressions. One search costs 1 Firecrawl credit, about 20 seconds.

Usage:
  <py> ad_spy.py --market "Nashville" --out ads/nashville
      STR management ads in a market (tries the phrasings hosts and managers actually use)
  <py> ad_spy.py --query "airbnb co-host" --media video --out ads/cohost
      any keyword, video ads only
  <py> ad_spy.py --page 983153071555770 --out ads/elevay
      every active ad one advertiser is running (the page id is in ads.json after a search)
  <py> ad_spy.py --out ads/nashville --get 1,4,7
      download the creatives (image or video) of shortlist numbers 1, 4 and 7

Writes OUT/ads.json (every ad, ranked) and prints a numbered shortlist. Exit 0 = found ads,
2 = no Firecrawl key or nothing found (the message says what to do instead).
"""
import argparse
import concurrent.futures as cf
import datetime as dt
import json
import os
import pathlib
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

import kie   # the key lookup (skill .env, cwd, home, the Connections kit) and UTF-8 console setup

FIRECRAWL = "https://api.firecrawl.dev/v2/scrape"
LIBRARY = "https://www.facebook.com/ads/library/"
MEDIA = {"all": "all", "image": "image_and_meme", "video": "video"}
# The phrasings STR managers advertise under, from the str-ad-spy research (2026-09-17/18,
# nine markets). The phrase that works varies: in 4 of 9 markets the obvious one returned
# zero, so a market search runs the whole ladder, led by what the market rents. Never
# "<market> property management": it matched 9,089 ads nationally and none in the market.
LADDERS = {
    "city": ["{m} short term rental management", "{m} airbnb management", "{m} STR management",
             "{m} vacation rental management", "{m} co-host"],
    "beach": ["{m} vacation rental management", "{m} short term rental management",
              "{m} airbnb management", "{m} co-host"],
    "mountain": ["{m} cabin rental management", "{m} vacation rental management",
                 "{m} short term rental management", "{m} airbnb management", "{m} co-host"],
}
# When every owner-facing phrase is empty, the market sells to guests (Jersey Shore, 2026-09-18).
GUEST_LADDER = {"city": ["{m} vacation rental", "{m} book direct"],
                "beach": ["{m} summer rental", "{m} beach house", "{m} book direct"],
                "mountain": ["{m} cabin", "{m} cabin rental", "{m} book direct"]}
NATIONAL = 500     # more results than this = the phrase was too common and ignored the market
# An ad has to talk about short-term rentals to be a competitor ("co-host" also matches a
# concert and a health testimonial, measured 2026-09-28), so plain words like "host" or
# "property" are not enough on their own.
STR_TALK = re.compile(r"airbnb|vrbo|short[- ]term|vacation[- ]rental|\bstrs?\b|rental propert|rental income|"
                      r"property manag|rental manag|hospitality manag|cabin rental|co-?host(ing)? (your|for)|"
                      r"book direct|nightly|occupancy|revpar|\badr\b|superhost|guest service|5-star|"
                      r"should be earning|comparable properties|home could pay|your listing|\ba guest\b|"
                      r"vacation home|propertymgmt|property-management|"
                      r"administramos tu propiedad|gestionamos cada propiedad|alquiler(es)? vacacional|"
                      r"renta(s)? (corta|vacacional)", re.I)
TEMPLATE = re.compile(r"\{\{[^}]*\}\}")    # dynamic ads: Meta fills these per viewer


def real_text(*candidates):
    """The first candidate that is real copy, not a dynamic-ad placeholder like {{product.brand}}."""
    for c in candidates:
        if isinstance(c, str) and c.strip() and not TEMPLATE.fullmatch(c.strip()):
            return TEMPLATE.sub("", c).strip()
    return ""
NOISE = ("pricelabs", "guesty", "hostaway", "airdna", "hospitable", "lodgify", "ownerrez", "wheelhouse",
         "arbitrage", "free training", "masterclass", "bootcamp", "mastermind", "course", "webinar",
         "cost segregation", "dscr", "mortgage", "lender")


class SpyError(RuntimeError):
    """fatal=True stops the whole run (bad key, no credits); otherwise one phrase failed."""
    def __init__(self, msg, fatal=False):
        super().__init__(msg)
        self.fatal = fatal


def firecrawl_key():
    k = os.environ.get("FIRECRAWL_API_KEY", "").strip()
    if k:
        return k, "FIRECRAWL_API_KEY environment variable"
    for p in kie.key_search_paths():
        k = kie._read_env_file(p).get("FIRECRAWL_API_KEY", "")
        if k:
            return k, str(p)
    raise SpyError("No FIRECRAWL_API_KEY found (the STR Secrets Connections kit sets it up; "
                   "or add FIRECRAWL_API_KEY=... to " + str(kie.SKILL_DIR / ".env") + "). "
                   "Without it, use the Meta Ads connector's ads_library_search as described in ADS.md.")


def library_url(query=None, page_id=None, media="all", country="US", active=True):
    q = {"active_status": "active" if active else "all", "ad_type": "all", "country": country,
         "is_targeted_country": "false", "media_type": MEDIA[media],
         "sort_data[direction]": "desc", "sort_data[mode]": "total_impressions"}
    if page_id:
        q.update({"search_type": "page", "view_all_page_id": str(page_id)})
    else:
        q.update({"search_type": "keyword_unordered", "q": query})
    return LIBRARY + "?" + urllib.parse.urlencode(q)


def scrape(url, key, tries=2):
    body = {"url": url, "formats": ["rawHtml", "markdown"], "onlyMainContent": False,
            "waitFor": 6000, "timeout": 90000,
            "actions": [{"type": "scroll", "direction": "down"}, {"type": "wait", "milliseconds": 2500},
                        {"type": "scroll", "direction": "down"}, {"type": "wait", "milliseconds": 2500}]}
    last = None
    for attempt in range(1, tries + 1):
        req = urllib.request.Request(FIRECRAWL, data=json.dumps(body).encode(),
                                     headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=180) as r:
                d = json.loads(r.read().decode("utf-8", "replace"))
            data = d.get("data") or {}
            html = data.get("rawHtml") or ""
            if html:
                return html, data.get("markdown") or ""
            last = SpyError(f"Firecrawl returned no page ({str(d)[:160]})")
        except urllib.error.HTTPError as e:
            msg = e.read()[:200].decode("utf-8", "replace")
            if e.code in (401, 403):
                raise SpyError(f"Firecrawl rejected the key (HTTP {e.code}). Check FIRECRAWL_API_KEY.", fatal=True)
            if e.code == 402:
                raise SpyError("The Firecrawl account is out of credits (HTTP 402).", fatal=True)
            last = SpyError(f"Firecrawl HTTP {e.code}: {msg}")
        except (urllib.error.URLError, TimeoutError, OSError, ValueError) as e:
            last = SpyError(f"could not reach Firecrawl ({e})")
        time.sleep(3 * attempt)
    raise last


def _decode_lists(html, marker):
    dec = json.JSONDecoder()
    i = 0
    while True:
        i = html.find(marker, i)
        if i < 0:
            return
        j = i + len(marker)
        try:
            val, _ = dec.raw_decode(html, j)
            yield val
        except ValueError:
            pass
        i = j


def _date(ts):
    try:
        return dt.datetime.fromtimestamp(int(ts), dt.timezone.utc).strftime("%Y-%m-%d")
    except (TypeError, ValueError, OSError):
        return None


def parse_ads(html):
    """Every ad in the page's own data, one dict each. Pure, tested."""
    out, seen = [], set()
    for group in _decode_lists(html, '"collated_results":'):
        if not isinstance(group, list):
            continue
        for ad in group:
            if not isinstance(ad, dict) or not ad.get("ad_archive_id"):
                continue
            aid = str(ad["ad_archive_id"])
            if aid in seen:
                continue
            seen.add(aid)
            s = ad.get("snapshot") or {}
            cards = [c for c in (s.get("cards") or []) if isinstance(c, dict)]
            body = real_text((s.get("body") or {}).get("text") if isinstance(s.get("body"), dict) else None,
                             *[c.get("body") for c in cards])
            dynamic = "{{" in json.dumps(s.get("body")) or "{{" in str(s.get("title"))
            images = [i.get("original_image_url") or i.get("resized_image_url") for i in (s.get("images") or [])
                      if isinstance(i, dict)]
            images += [c.get("original_image_url") or c.get("resized_image_url") for c in cards]
            videos = [v.get("video_hd_url") or v.get("video_sd_url") for v in (s.get("videos") or [])
                      if isinstance(v, dict)]
            videos += [c.get("video_hd_url") or c.get("video_sd_url") for c in cards]
            posters = [v.get("video_preview_image_url") for v in (s.get("videos") or []) if isinstance(v, dict)]
            posters += [c.get("video_preview_image_url") for c in cards]
            start = _date(ad.get("start_date"))
            days = None
            if start:
                days = (dt.datetime.now(dt.timezone.utc).date() - dt.date.fromisoformat(start)).days
            out.append({
                "id": aid,
                "page_name": s.get("page_name") or ad.get("page_name"),
                "page_id": str(ad.get("page_id") or s.get("page_id") or ""),
                "copies": ad.get("collation_count") or 1,
                "active": ad.get("is_active"),
                "start_date": start,
                "days_running": days,
                "format": "video" if any(videos) else (s.get("display_format") or "image").lower(),
                "platforms": ad.get("publisher_platform") or [],
                "title": real_text(s.get("title"), *[c.get("title") for c in cards]) or None,
                "body": body,
                "dynamic": dynamic,
                "cta": s.get("cta_text") or next((c.get("cta_text") for c in cards if c.get("cta_text")), None),
                "link": s.get("link_url") or next((c.get("link_url") for c in cards if c.get("link_url")), None),
                "images": [u for u in dict.fromkeys(images) if u],
                "videos": [u for u in dict.fromkeys(videos) if u],
                "posters": [u for u in dict.fromkeys(posters) if u],
                "snapshot_url": f"https://www.facebook.com/ads/library/?id={aid}",
            })
    return out


def total_count(html):
    m = re.search(r'"search_results_connection":\{"count":(\d+)', html)
    return int(m.group(1)) if m else None


def collapse(ads):
    """One row per creative: the same page running the same copy under several ad ids is one
    ad with more copies (more copies = more money behind it; Meta publishes no spend)."""
    groups = {}
    for a in ads:
        k = (a["page_id"], " ".join((a.get("body") or a.get("title") or a["id"]).split())[:160].lower())
        g = groups.get(k)
        if g is None:
            groups[k] = dict(a, ids=[a["id"]])
        else:
            g["copies"] = (g.get("copies") or 1) + (a.get("copies") or 1)
            g["ids"].append(a["id"])
            g["days_running"] = max(g.get("days_running") or 0, a.get("days_running") or 0)
            for f in ("images", "videos", "posters"):
                g[f] = list(dict.fromkeys(g[f] + a[f]))
    return list(groups.values())


def tag(ads, market=None):
    """noise = software, courses, lenders (not competitors); local = names the market."""
    words = re.findall(r"[a-z]{3,}", (market or "").lower())     # "St. George" -> ["george"]
    for a in ads:
        text = " ".join([a.get("page_name") or "", a.get("title") or "", a.get("body") or "",
                         a.get("link") or ""]).lower()
        a["noise"] = any(n in text for n in NOISE) or not STR_TALK.search(text)
        a["local"] = (not words) or words[0] in text
    return ads


def rank(ads):
    """Competitors before noise, ads that name the market first, then the spend proxy
    (copies of the same creative running), then how long it has run."""
    return sorted(ads, key=lambda a: (bool(a.get("noise")), not a.get("local", True),
                                      -(a.get("copies") or 1), -(a.get("days_running") or 0)))


def one_line(text, n=110):
    t = " ".join((text or "").split())
    return t if len(t) <= n else t[:n - 3] + "..."


def show(ads, limit):
    for n, a in enumerate(ads[:limit], 1):
        run = f"{a['days_running']}d" if a.get("days_running") is not None else "?"
        mark = "  (not a competitor)" if a.get("noise") else ("" if a.get("local", True) else "  (other market?)")
        print(f"{n:2d}. {one_line(a['page_name'], 34):<34} {a['format']:<8} x{a['copies']:<3} {run:>5}  "
              f"{one_line(a['body'] or a.get('title') or ('(dynamic ad: the text changes per viewer, open ' + a['snapshot_url'] + ')' if a.get('dynamic') else ''), 90)}{mark}")


def download(url, dest):
    req = urllib.request.Request(url, headers={"User-Agent": kie.UA})
    with urllib.request.urlopen(req, timeout=300) as r:
        data = r.read()
    if len(data) < 2000:
        raise SpyError(f"only {len(data)} bytes")
    dest.write_bytes(data)
    return len(data)


def get_creatives(out, picks):
    try:
        ads = json.loads((out / "ads.json").read_text(encoding="utf-8"))["ads"]
    except (OSError, ValueError, KeyError):
        raise SpyError(f"no search results in {out} yet: run a search with --out {out} first")
    dest = out / "creatives"
    dest.mkdir(parents=True, exist_ok=True)
    jobs = []
    for n in picks:
        if not 1 <= n <= len(ads):
            raise SpyError(f"--get: {n} is not a shortlist number between 1 and {len(ads)}")
        a = ads[n - 1]
        for k, u in enumerate(a["videos"], 1):
            jobs.append((u, dest / f"{n:02d}_{a['id']}_{k}.mp4"))
        if not a["videos"]:
            for k, u in enumerate(a["images"], 1):
                jobs.append((u, dest / f"{n:02d}_{a['id']}_{k}.jpg"))
        for k, u in enumerate(a["posters"][:1], 1):
            jobs.append((u, dest / f"{n:02d}_{a['id']}_poster.jpg"))
        (dest / f"{n:02d}_{a['id']}.txt").write_text(
            f"{a['page_name']}\n{a['snapshot_url']}\nstarted {a['start_date']}, {a['copies']} copies running\n"
            f"CTA: {a['cta']}\nLink: {a['link']}\nTitle: {a['title']}\n\n{a['body']}\n", encoding="utf-8")

    def one(job):
        u, d = job
        try:
            return d, download(u, d), None
        except (SpyError, urllib.error.URLError, TimeoutError, OSError) as e:
            return d, 0, str(e)
    ok, saved = 0, []
    with cf.ThreadPoolExecutor(6) as ex:
        for d, size, err in ex.map(one, jobs):
            if err:
                print(f"  FAIL  {d.name}: {err}")
            else:
                ok += 1
                saved.append(d)
    # A dynamic ad lists every size and placement of the same picture (Austin, 2026-09-29:
    # 16 images, 14 byte-identical). Keep one of each so there is less to look at.
    dupes = drop_duplicates(saved)
    for d in saved:
        if d not in dupes:
            print(f"  OK    {d}  ({d.stat().st_size / 1e6:.1f} MB)")
    note = f", {len(dupes)} identical copies removed" if dupes else ""
    print(f"{ok - len(dupes)} files in {dest}{note} (each ad's copy is in its .txt). "
          "Facebook's media links expire in a few days: download what you need now.")
    return 0 if ok else 1


def drop_duplicates(paths):
    """Delete files whose bytes match an earlier one. Returns the deleted paths."""
    import hashlib
    seen, gone = set(), []
    for p in sorted(paths):
        h = hashlib.sha1(p.read_bytes()).hexdigest()
        if h in seen:
            p.unlink()
            gone.append(p)
        else:
            seen.add(h)
    return gone


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--market", help="a city or area: finds the STR managers advertising there")
    g.add_argument("--query", action="append", help="a keyword search (repeatable)")
    g.add_argument("--page", help="an advertiser's page id: every ad they are running")
    ap.add_argument("--kind", choices=sorted(LADDERS), default="city",
                    help="market mode: what the market rents (city, beach, mountain); picks the phrases")
    ap.add_argument("--media", choices=sorted(MEDIA), default="all")
    ap.add_argument("--country", default="US")
    ap.add_argument("--out", required=True, help="folder for ads.json and downloaded creatives")
    ap.add_argument("--show", type=int, default=15, help="how many to list (default 15)")
    ap.add_argument("--get", default="", help="comma list of shortlist numbers to download")
    a = ap.parse_args(argv)
    out = pathlib.Path(a.out)
    try:
        if a.get:
            try:
                picks = [int(x) for x in a.get.split(",") if x.strip()]
            except ValueError:
                raise SpyError(f"--get takes shortlist numbers like 1,4,7 (got {a.get!r})")
            return get_creatives(out, picks)
        if not (a.market or a.query or a.page):
            ap.error("give --market, --query or --page (or --get after a search)")
        key, where = firecrawl_key()
        if a.market:
            searches = [t.format(m=a.market) for t in LADDERS[a.kind]]
        elif a.query:
            searches = a.query
        else:
            searches = [None]
        ads, used = [], []

        def search(q):
            url = library_url(query=q, page_id=a.page, media=a.media, country=a.country)
            # Sometimes the page comes back before Meta has loaded its results (measured
            # 2026-09-28: 1 empty page, then 3 full ones for the same search). No result data at
            # all means "not loaded", so scrape again; a real zero says count 0.
            try:
                for attempt in range(3):
                    html, _ = scrape(url, key)
                    found = parse_ads(html)
                    if found or total_count(html) == 0:
                        break
            except SpyError as e:
                if e.fatal:
                    raise
                return q, [], None, str(e)     # one phrase failing never loses the others
            return q, found, total_count(html), None

        errors = []

        def run(phrases):
            with cf.ThreadPoolExecutor(3) as ex:
                for q, found, count, err in ex.map(search, phrases):
                    label = q or "page " + a.page
                    if err:
                        errors.append(err)
                        print(f"  {label}: failed ({err}); the other phrases still count", flush=True)
                        continue
                    if a.market and count and count > NATIONAL:
                        print(f"  {label}: {count} results = a national query, ignored", flush=True)
                        continue
                    print(f"  {label}: {len(found)} ads" + (f" (Meta counts {count})" if count is not None else ""),
                          flush=True)
                    if found:
                        used.append(q)
                    ads.extend(found)

        print("searching the Ad Library ...", flush=True)
        run(searches)
        if a.market and not ads:
            print("no owner-facing ads: trying what operators here say to guests ...", flush=True)
            run([t.format(m=a.market) for t in GUEST_LADDER[a.kind]])
        uniq = {x["id"]: x for x in ads}
        ads = rank(tag(collapse(list(uniq.values())), a.market))
        if not ads and errors:
            raise SpyError(f"every search failed ({errors[0]}). Check the internet connection and try again.")
        if not ads:
            print("ERROR: no ads found. Try a wider term (\"airbnb management\", \"vacation rental\"), "
                  "the whole state, or --media all. Meta's page may also have changed: then use the Meta "
                  "Ads connector's ads_library_search (ADS.md, fallback).")
            return 2
        out.mkdir(parents=True, exist_ok=True)
        (out / "ads.json").write_text(json.dumps({
            "searched": searches if not a.page else [f"page {a.page}"], "found_with": used, "media": a.media,
            "country": a.country, "when": dt.datetime.now().strftime("%Y-%m-%d %H:%M"),
            "firecrawl_key_from": where, "ads": ads}, indent=1, ensure_ascii=False), encoding="utf-8")
        advertisers = len({x["page_id"] for x in ads})
        print(f"\n{len(ads)} ads from {advertisers} advertisers, strongest first "
              "(xN = copies of the creative running, the spend signal; d = days running):")
        show(ads, a.show)
        print(f"\nsaved {out / 'ads.json'} (full copy, links, media). Next: --get 1,3 to download creatives.")
        return 0
    except SpyError as e:
        print(f"ERROR: {e}")
        return 2


if __name__ == "__main__":
    sys.exit(main())
