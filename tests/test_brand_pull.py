"""Offline tests for brand_pull.py helpers (no browser, no network).
Run:  python3 -m unittest discover -s tests -v
"""
import pathlib
import sys
import unittest

SCRIPTS = pathlib.Path(__file__).resolve().parent.parent / "skill" / "str-secrets-content-studio" / "scripts"
sys.path.insert(0, str(SCRIPTS))

try:
    from PIL import Image
    HAVE_PIL = True
except ImportError:  # pragma: no cover
    HAVE_PIL = False
if HAVE_PIL:
    import brand_pull  # noqa: E402


@unittest.skipUnless(HAVE_PIL, "Pillow not installed")
class ToAlpha(unittest.TestCase):
    def test_dark_logo_on_white_box_becomes_transparent(self):
        im = Image.new("RGB", (300, 120), "white")
        im.paste((20, 20, 20), (40, 30, 260, 90))
        a = brand_pull.to_alpha(im)
        self.assertIsNotNone(a)
        self.assertEqual(a.mode, "RGBA")
        self.assertEqual(a.size, (220, 60))  # cropped to the mark
        self.assertGreater(a.getpixel((100, 30))[3], 240)

    def test_light_logo_on_black_box(self):
        im = Image.new("RGB", (300, 120), "black")
        im.paste((250, 250, 250), (100, 40, 200, 80))
        a = brand_pull.to_alpha(im)
        self.assertEqual(a.size, (100, 40))
        self.assertGreater(a.getpixel((50, 20))[3], 240)

    def test_real_alpha_is_kept(self):
        im = Image.new("RGBA", (200, 100), (0, 0, 0, 0))
        im.paste((200, 30, 30, 255), (50, 25, 150, 75))
        a = brand_pull.to_alpha(im)
        self.assertEqual(a.size, (100, 50))
        self.assertEqual(a.getpixel((10, 10)), (200, 30, 30, 255))

    def test_blank_or_photo_like_images_are_refused(self):
        self.assertIsNone(brand_pull.to_alpha(Image.new("RGB", (200, 100), "white")))
        self.assertIsNone(brand_pull.to_alpha(Image.new("RGB", (200, 100), (128, 110, 90))))  # mid-tone box


@unittest.skipUnless(HAVE_PIL, "Pillow not installed")
class SuggestedCta(unittest.TestCase):
    def test_booking_button_becomes_a_line_with_the_domain(self):
        cands = [{"text": "Explore Our Stays", "href": "/stays"}, {"text": "BOOK YOUR STAY", "href": "/book"}]
        self.assertEqual(brand_pull.suggest_cta(cands, "www.lakeviewcabins.com"),
                         "Book your stay at lakeviewcabins.com")

    def test_first_booking_word_wins_over_generic_links(self):
        cands = [{"text": "About us", "href": "/about"}, {"text": "Check availability", "href": "/a"}]
        self.assertEqual(brand_pull.suggest_cta(cands, "lakehouse.com"), "Check availability at lakehouse.com")

    def test_nothing_bookable_means_no_suggestion(self):
        self.assertIsNone(brand_pull.suggest_cta([{"text": "About us", "href": "/about"}], "x.com"))
        self.assertIsNone(brand_pull.suggest_cta([], "x.com"))


@unittest.skipUnless(HAVE_PIL, "Pillow not installed")
class Palette(unittest.TestCase):
    def test_merges_near_duplicates_and_ranks_by_area(self):
        p = brand_pull.palette([("#FFFFFF", 500), ("#FEFEFE", 300), ("#8A8C6D", 150), ("#000000", 50)])
        self.assertEqual(p[0][0], "#FFFFFF")
        self.assertAlmostEqual(p[0][1], 0.8, places=2)
        self.assertEqual([h for h, _ in p], ["#FFFFFF", "#8A8C6D", "#000000"])

    def test_css_colour_parsing(self):
        self.assertEqual(brand_pull.css_hex("rgb(138, 140, 109)"), "#8A8C6D")
        self.assertEqual(brand_pull.css_hex("rgba(0, 0, 0, 0)"), None)  # transparent
        self.assertEqual(brand_pull.css_hex("rgba(10, 20, 30, 0.9)"), "#0A141E")


if __name__ == "__main__":
    unittest.main()
