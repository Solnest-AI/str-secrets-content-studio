"""Offline tests for Ad Spy (ad_spy.py) and the ad cloner (ad_make.py). No network, no credits.
Run:  python3 -m unittest discover -s tests -v
"""
import io
import json
import pathlib
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from unittest import mock

ROOT = pathlib.Path(__file__).resolve().parent.parent
SKILL = ROOT / "skill" / "str-secrets-content-studio"
sys.path.insert(0, str(SKILL / "scripts"))

import ad_make  # noqa: E402
import ad_spy  # noqa: E402


def _ad(aid, page, body, copies=1, start=1788300000, videos=None, images=None, title=None):
    snap = {"page_name": page, "page_id": page, "body": {"text": body}, "title": title,
            "cta_text": "Learn more", "link_url": "https://example.com", "cards": [],
            "images": [{"original_image_url": u} for u in (images or [])],
            "videos": [{"video_hd_url": u, "video_preview_image_url": u + ".jpg"} for u in (videos or [])]}
    return {"ad_archive_id": aid, "collation_count": copies, "page_id": page, "is_active": True,
            "start_date": start, "publisher_platform": ["FACEBOOK"], "snapshot": snap}


def _page(ads, count=None):
    blob = json.dumps({"collated_results": ads}, separators=(",", ":"))
    head = f'"search_results_connection":{{"count":{count if count is not None else len(ads)},"edges":[' \
        if count is not None or ads else ""
    return "<html><script>" + head + blob[1:-1] + "</script></html>"


class Parse(unittest.TestCase):
    def test_every_ad_with_its_copy_media_and_dates(self):
        html = _page([_ad("1", "GoodNight Stay", "Your calendar shouldn't be your problem.",
                          images=["https://img/a.jpg"]),
                      _ad("2", "Cousinsbnb", "9:47pm. Your guest texts.", videos=["https://vid/b.mp4"])])
        ads = ad_spy.parse_ads(html)
        self.assertEqual([a["id"] for a in ads], ["1", "2"])
        self.assertEqual(ads[0]["body"], "Your calendar shouldn't be your problem.")
        self.assertEqual(ads[0]["images"], ["https://img/a.jpg"])
        self.assertEqual(ads[1]["format"], "video")
        self.assertEqual(ads[1]["videos"], ["https://vid/b.mp4"])
        self.assertEqual(ads[1]["posters"], ["https://vid/b.mp4.jpg"])
        self.assertTrue(ads[0]["start_date"].startswith("2026-"))
        self.assertIn("ads/library/?id=1", ads[0]["snapshot_url"])

    def test_dynamic_ads_use_their_card_text_not_the_placeholder(self):
        a = _ad("5", "Casiola", "{{product.brand}}", title="{{product.name}}")
        a["snapshot"]["cards"] = [{"body": "Tired of stressing about your vacation rental?", "title": "Earn more"}]
        b = _ad("6", "Plunj", "{{product.brand}}", title="{{product.name}}")
        ads = ad_spy.parse_ads(_page([a, b]))
        self.assertEqual(ads[0]["body"], "Tired of stressing about your vacation rental?")
        self.assertEqual(ads[0]["title"], "Earn more")
        self.assertTrue(ads[0]["dynamic"])
        self.assertEqual((ads[1]["body"], ads[1]["title"]), ("", None))   # no card text: shown as dynamic

    def test_spanish_and_listing_quality_ads_count_as_competitors(self):
        ads = ad_spy.parse_ads(_page([
            _ad("1", "Marba", "Administramos tu propiedad solo en Miami, gestionamos cada propiedad."),
            _ad("2", "Casago", "Your listing is the only thing a guest sees before they decide.")]))
        self.assertEqual([a["noise"] for a in ad_spy.tag(ads, "Miami")], [False, False])

    def test_the_same_ad_twice_on_the_page_is_one_ad(self):
        a = _ad("7", "X", "hello")
        html = _page([a]) + _page([a])
        self.assertEqual(len(ad_spy.parse_ads(html)), 1)

    def test_a_page_without_data_is_empty_not_a_crash(self):
        self.assertEqual(ad_spy.parse_ads("<html>login</html>"), [])
        self.assertIsNone(ad_spy.total_count("<html></html>"))
        self.assertEqual(ad_spy.total_count('"search_results_connection":{"count":14,'), 14)


class Rank(unittest.TestCase):
    def test_duplicate_creatives_collapse_into_copies(self):
        ads = ad_spy.parse_ads(_page([_ad("1", "P", "Same copy here", copies=2),
                                      _ad("2", "P", "Same   copy here", copies=1),
                                      _ad("3", "Q", "Other copy")]))
        rows = ad_spy.collapse(ads)
        self.assertEqual(len(rows), 2)
        p = next(r for r in rows if r["page_id"] == "P")
        self.assertEqual(p["copies"], 3)
        self.assertEqual(sorted(p["ids"]), ["1", "2"])

    def test_competitors_first_then_local_then_spend(self):
        ads = ad_spy.parse_ads(_page([
            _ad("1", "PriceLabs", "Nashville pricing software for your Airbnb", copies=9),
            _ad("2", "Concert Hall", "A romantic evening of music in Nashville", copies=5),
            _ad("3", "Elsewhere Co", "Short term rental management in Denver", copies=4),
            _ad("4", "GoodNight", "Nashville airbnb owners: keep your calendar full", copies=2),
            _ad("5", "Casago", "What should your Nashville vacation rental earn?", copies=1),
            _ad("6", "Julie", "My nephrologist wrote three words in my chart. Nashville clinic.", copies=3)]))
        ranked = ad_spy.rank(ad_spy.tag(ad_spy.collapse(ads), "Nashville"))
        names = [a["page_name"] for a in ranked]
        self.assertEqual(names[:3], ["GoodNight", "Casago", "Elsewhere Co"])
        self.assertTrue(next(a for a in ranked if a["page_name"] == "PriceLabs")["noise"])
        self.assertTrue(next(a for a in ranked if a["page_name"] == "Concert Hall")["noise"])
        self.assertFalse(next(a for a in ranked if a["page_name"] == "Elsewhere Co")["local"])
        self.assertTrue(next(a for a in ranked if a["page_name"] == "Julie")["noise"])   # off-topic, measured

    def test_market_ladders_never_use_property_management(self):
        for kind, phrases in ad_spy.LADDERS.items():
            self.assertTrue(phrases, kind)
            for p in phrases + ad_spy.GUEST_LADDER[kind]:
                self.assertNotIn("property management", p)
                self.assertIn("{m}", p)

    def test_library_url_shapes(self):
        u = ad_spy.library_url(query="Nashville airbnb management", media="video")
        self.assertIn("search_type=keyword_unordered", u)
        self.assertIn("media_type=video", u)
        self.assertIn("sort_data%5Bmode%5D=total_impressions", u)
        p = ad_spy.library_url(page_id="123")
        self.assertIn("view_all_page_id=123", p)


class Downloads(unittest.TestCase):
    def test_identical_creatives_are_kept_once(self):
        with tempfile.TemporaryDirectory() as t:
            d = pathlib.Path(t)
            files = []
            for i, data in enumerate([b"A" * 3000, b"A" * 3000, b"B" * 3000, b"A" * 3000], 1):
                p = d / f"01_x_{i}.jpg"
                p.write_bytes(data)
                files.append(p)
            gone = ad_spy.drop_duplicates(files)
            self.assertEqual(sorted(x.name for x in gone), ["01_x_2.jpg", "01_x_4.jpg"])
            self.assertEqual(sorted(x.name for x in d.iterdir()), ["01_x_1.jpg", "01_x_3.jpg"])


class SearchFlow(unittest.TestCase):
    def test_a_national_query_is_ignored_and_an_empty_page_is_scraped_again(self):
        good = _page([_ad("1", "GoodNight", "Nashville airbnb owners, keep your calendar full")], count=3)
        national = _page([_ad("9", "Big", "rental stuff")], count=9089)
        empty = "<html>still loading</html>"
        calls = []

        def fake_scrape(url, key, tries=2):
            calls.append(url)
            if "short+term" in url:
                return national, ""
            if len([c for c in calls if "airbnb" in c]) == 1 and "airbnb" in url:
                return empty, ""
            return good, ""
        with tempfile.TemporaryDirectory() as t, \
                mock.patch.object(ad_spy, "firecrawl_key", return_value=("k", "test")), \
                mock.patch.object(ad_spy, "scrape", side_effect=fake_scrape), \
                mock.patch.object(ad_spy, "LADDERS", {"city": ["{m} short term rental management",
                                                               "{m} airbnb management"]}), \
                redirect_stdout(io.StringIO()) as buf:
            rc = ad_spy.main(["--market", "Nashville", "--out", t])
            data = json.loads((pathlib.Path(t) / "ads.json").read_text(encoding="utf-8"))
        self.assertEqual(rc, 0)
        self.assertIn("national query, ignored", buf.getvalue())
        self.assertEqual([a["id"] for a in data["ads"]], ["1"])
        self.assertEqual(data["found_with"], ["Nashville airbnb management"])

    def test_no_key_is_a_plain_message_with_the_fallback(self):
        with tempfile.TemporaryDirectory() as t, \
                mock.patch.dict("os.environ", {}, clear=True), \
                mock.patch.object(ad_spy.kie, "key_search_paths", return_value=[pathlib.Path(t) / ".env"]), \
                redirect_stdout(io.StringIO()) as buf:
            rc = ad_spy.main(["--query", "x", "--out", t])
        self.assertEqual(rc, 2)
        self.assertIn("FIRECRAWL_API_KEY", buf.getvalue())
        self.assertIn("ads_library_search", buf.getvalue())


class Make(unittest.TestCase):
    def test_dry_run_prices_and_spends_nothing(self):
        with tempfile.TemporaryDirectory() as t:
            spec = pathlib.Path(t) / "spec.txt"
            spec.write_text("CONSTRAINTS: render only this. " * 5, encoding="utf-8")
            with mock.patch.object(ad_make.kie, "credits", return_value=500.0), \
                    mock.patch.object(ad_make.kie, "create_task") as ct, \
                    mock.patch.object(ad_make.kie, "upload") as up, redirect_stdout(io.StringIO()) as buf:
                rc = ad_make.main(["--spec", str(spec), "--count", "3", "--out", t, "--name", "a1", "--dry-run"])
        self.assertEqual(rc, 0)
        self.assertIn("3 image(s) = 18 credits", buf.getvalue())
        self.assertEqual(ct.call_count + up.call_count, 0)

    def test_not_enough_credits_stops_before_spending(self):
        with tempfile.TemporaryDirectory() as t:
            spec = pathlib.Path(t) / "spec.txt"
            spec.write_text("x" * 100, encoding="utf-8")
            with mock.patch.object(ad_make.kie, "credits", return_value=2.0), \
                    mock.patch.object(ad_make.kie, "create_task") as ct, redirect_stdout(io.StringIO()):
                rc = ad_make.main(["--spec", str(spec), "--out", t, "--name", "a1"])
        self.assertEqual(rc, 1)
        self.assertEqual(ct.call_count, 0)

    def test_a_kie_failure_retries_and_a_finished_image_is_kept(self):
        with tempfile.TemporaryDirectory() as t:
            out = pathlib.Path(t)
            waits = [("fail", {"failMsg": "Internal Error"}),
                     ("success", {"resultJson": json.dumps({"resultUrls": ["u"]})})]

            def fake_download(url, dest, kind="image", tries=3):
                pathlib.Path(dest).write_bytes(b"\x89PNG" + b"0" * 2000)
                return 2004
            state = {}
            with mock.patch.object(ad_make.kie, "create_task", side_effect=["T1", "T2"]) as ct, \
                    mock.patch.object(ad_make.kie, "wait_task", side_effect=waits), \
                    mock.patch.object(ad_make.kie, "download", side_effect=fake_download), \
                    mock.patch.object(ad_make.time, "sleep"), redirect_stdout(io.StringIO()):
                r = ad_make.run_task(out, state, "a1_1", {"model": "m"}, out / "a1_1.png")
                self.assertTrue(r["ok"])
                self.assertEqual(ct.call_count, 2)
                again = ad_make.run_task(out, state, "a1_1", {"model": "m"}, out / "a1_1.png")
                self.assertEqual(ct.call_count, 2)      # kept, not paid again
            self.assertEqual(again["task"], "T2")

    def test_references_must_exist(self):
        with tempfile.TemporaryDirectory() as t:
            spec = pathlib.Path(t) / "spec.txt"
            spec.write_text("x" * 100, encoding="utf-8")
            with redirect_stdout(io.StringIO()) as buf:
                rc = ad_make.main(["--spec", str(spec), "--ref", str(pathlib.Path(t) / "nope.jpg"),
                                   "--out", t, "--name", "a1"])
        self.assertEqual(rc, 1)
        self.assertIn("reference not found", buf.getvalue())


class Docs(unittest.TestCase):
    def test_skill_routes_ads_and_no_video_ad_or_avatar_path_ships(self):
        skill = (SKILL / "SKILL.md").read_text(encoding="utf-8")
        ads = (SKILL / "ADS.md").read_text(encoding="utf-8")
        self.assertIn("ADS.md", skill)
        for word in ("avatar", "higgsfield", "lip-sync", "lip sync"):
            self.assertNotIn(word, ads.lower())
            self.assertNotIn(word, (SKILL / "scripts" / "ad_make.py").read_text(encoding="utf-8").lower())
        self.assertIn("property management", ads)          # the warning is there
        self.assertIn("--dry-run", ads)

    def test_every_script_command_in_ads_md_exists(self):
        ads = (SKILL / "ADS.md").read_text(encoding="utf-8")
        import re
        for name in set(re.findall(r'\$SCRIPTS/([a-z_]+\.py)', ads)):
            self.assertTrue((SKILL / "scripts" / name).is_file(), name)


if __name__ == "__main__":
    unittest.main()
