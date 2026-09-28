"""Offline tests for listing_pull.py (no browser, no network).
Run:  python3 -m unittest discover -s tests -v
"""
import json
import pathlib
import sys
import tempfile
import unittest

SCRIPTS = pathlib.Path(__file__).resolve().parent.parent / "skill" / "str-secrets-content-studio" / "scripts"
sys.path.insert(0, str(SCRIPTS))

try:
    from PIL import Image
    HAVE_PIL = True
except ImportError:  # pragma: no cover
    HAVE_PIL = False
if HAVE_PIL:
    import listing_pull  # noqa: E402

# innerText shaped exactly like Airbnb review cards (made-up guests, real card layout)
ITEMS = [
    "Jordan\nNelson, Canada\nRating, 5 stars\n,\n·\n3 weeks ago\n,\n·\nStayed with a pet\nI can’t say "
    "enough good things about this place. The kids loved the hot tub.\nShow more",
    "Priya\n1 month on Airbnb\nRating, 5 stars\n,\n·\nAugust 2026\n,\n·\nStayed with a pet\nGreat views and "
    "a very easy stay\nShow more",
    "Dan\n6 years on Airbnb\nRating, 4 stars\n,\n·\nJuly 2026\nGreat view.\n\nNoisy construction next door.\n"
    "Response from host:\nThanks Dan!",
]
LID = "1734384025235879146"


@unittest.skipUnless(HAVE_PIL, "Pillow not installed")
class Reviews(unittest.TestCase):
    def test_real_items_parse(self):
        r = listing_pull.parse_reviews(ITEMS)
        self.assertEqual([x["author"] for x in r], ["Jordan", "Priya", "Dan"])
        self.assertEqual(r[0]["location"], "Nelson, Canada")
        self.assertIsNone(r[1]["location"])  # "1 month on Airbnb" is not a place
        self.assertEqual([x["rating"] for x in r], [5, 5, 4])
        self.assertEqual(r[0]["when"], "3 weeks ago")
        self.assertTrue(r[0]["text"].startswith("I can’t say"))
        self.assertNotIn("Show more", r[0]["text"])
        self.assertNotIn("Stayed with a pet", r[1]["text"])
        self.assertEqual(r[1]["text"], "Great views and a very easy stay")

    def test_host_response_is_not_part_of_the_review(self):
        r = listing_pull.parse_reviews(ITEMS)[2]
        self.assertIn("Noisy construction", r["text"])
        self.assertNotIn("Thanks Dan", r["text"])

    def test_garbage_items_are_skipped(self):
        self.assertEqual(listing_pull.parse_reviews(["", "Show more", "Just a name"]), [])


@unittest.skipUnless(HAVE_PIL, "Pillow not installed")
class PhotosAndAmenities(unittest.TestCase):
    def test_photo_urls_dedupe_and_keep_this_listing_only(self):
        a = f"https://a0.muscache.com/im/pictures/hosting/Hosting-{LID}/original/aaa-111.jpeg"
        b = f"https://a0.muscache.com/im/pictures/miso/Hosting-{LID}/original/bbb-222.jpeg"
        other = "https://a0.muscache.com/im/pictures/hosting/Hosting-999/original/ccc-333.jpeg"
        html = f'"{a}?im_w=720" "{b}" "{a}" "{other}"'
        self.assertEqual(listing_pull.photo_urls(html, LID), [a, b])

    def test_amenities_available_only(self):
        blob = {"seeAllAmenitiesGroups": [{"title": "Outdoor", "amenities": [
            {"title": "Shared hot tub", "available": True},
            {"title": "Private pool", "available": False}]}]}
        html = "<script>" + json.dumps(blob)[1:-1] + ",\"x\":1}</script>"
        self.assertEqual(listing_pull.amenity_titles(html), ["Shared hot tub"])

    def test_null_amenity_lists_are_empty_not_a_crash(self):
        html = '<script>{"seeAllAmenitiesGroups":[{"title":"x","amenities":null},null,{"amenities":[{"title":"Wifi","available":true}]}]}</script>'
        self.assertEqual(listing_pull.amenity_titles(html), ["Wifi"])

    def test_non_image_download_is_not_left_on_disk(self):
        d = pathlib.Path(tempfile.mkdtemp())
        class R:
            def __enter__(self): return self
            def __exit__(self, *a): return False
            def read(self): return b"<html>" + b"x" * 20000 + b"</html>"
        from unittest import mock
        with mock.patch.object(listing_pull.urllib.request, "urlopen", return_value=R()), \
                mock.patch.object(listing_pull.time, "sleep"):
            self.assertFalse(listing_pull.fetch("https://example.com/a.jpg", d / "01.jpg"))
        self.assertFalse((d / "01.jpg").exists())

    def test_amenities_missing_is_empty_not_a_crash(self):
        self.assertEqual(listing_pull.amenity_titles("<html></html>"), [])


@unittest.skipUnless(HAVE_PIL, "Pillow not installed")
class Pull(unittest.TestCase):
    def test_blocked_or_empty_page_exits_2(self):
        out = pathlib.Path(tempfile.mkdtemp())
        fake = lambda url: {"html": "<html>captcha</html>", "sections": {}, "reviews": [], "url": url}
        rc = listing_pull.pull_url(f"https://www.airbnb.com/rooms/{LID}", out, render=fake)
        self.assertEqual(rc, 2)

    def test_folder_mode_numbers_photos_and_needs_some(self):
        src = pathlib.Path(tempfile.mkdtemp())
        out = pathlib.Path(tempfile.mkdtemp())
        self.assertEqual(listing_pull.pull_folder(src, out), 2)  # empty folder
        for n, colour in (("b.png", "red"), ("a.jpg", "blue"), ("notes.txt", None)):
            if colour:
                Image.new("RGB", (1600, 1200), colour).save(src / n)
            else:
                (src / n).write_text("hello")
        (src / "desc.txt").write_text("Lake view. Hot tub.", encoding="utf-8")
        self.assertEqual(listing_pull.pull_folder(src, out, facts_file=src / "desc.txt", minimum=2), 0)
        full = sorted(p.name for p in (out / "source/full").iterdir())
        self.assertEqual(full, ["01.jpg", "02.jpg"])  # a.jpg first, the txt ignored
        self.assertTrue((out / "source/_sheet.jpg").exists())
        self.assertIn("Hot tub", (out / "source/facts.txt").read_text(encoding="utf-8"))
        self.assertEqual(json.loads((out / "source/reviews.json").read_text()), [])


if __name__ == "__main__":
    unittest.main()
