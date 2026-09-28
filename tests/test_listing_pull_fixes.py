"""Codex review 2026-09-28, listing_pull: older Airbnb photo URLs and reruns that mix
listings. Offline. Run: python3 -m unittest discover -s tests -v
"""
import pathlib
import sys
import tempfile
import unittest
from unittest import mock

SCRIPTS = pathlib.Path(__file__).resolve().parent.parent / "skill" / "str-secrets-content-studio" / "scripts"
sys.path.insert(0, str(SCRIPTS))

try:
    from PIL import Image
    HAVE_PIL = True
except ImportError:  # pragma: no cover
    HAVE_PIL = False
if HAVE_PIL:
    import listing_pull  # noqa: E402

LID = "20874549"


@unittest.skipUnless(HAVE_PIL, "Pillow not installed")
class OlderListings(unittest.TestCase):
    def test_a_listing_without_hosting_ids_still_yields_its_photos(self):
        html = ('https:\\u002F\\u002Fa0.muscache.com\\u002Fim\\u002Fpictures\\u002F11111111-2222.jpg '
                '"https://a0.muscache.com/im/pictures/11111111-2222.jpg" '
                'https://a0.muscache.com/im/pictures/33333333-4444.jpeg '
                'https://a0.muscache.com/im/pictures/user/User-1/original/face.jpeg')
        urls, own = listing_pull.gallery_urls(html, LID)
        self.assertFalse(own)
        self.assertEqual(urls, ["https://a0.muscache.com/im/pictures/11111111-2222.jpg",
                                "https://a0.muscache.com/im/pictures/33333333-4444.jpeg"])

    def test_the_hosting_id_form_still_wins_when_present(self):
        a = f"https://a0.muscache.com/im/pictures/miso/Hosting-{LID}/original/aaa-111.jpeg"
        urls, own = listing_pull.gallery_urls(f'"{a}" https://a0.muscache.com/im/pictures/other.jpg', LID)
        self.assertTrue(own)
        self.assertEqual(urls, [a])


@unittest.skipUnless(HAVE_PIL, "Pillow not installed")
class Reruns(unittest.TestCase):
    def test_a_rerun_with_fewer_photos_leaves_no_old_ones_behind(self):
        out = pathlib.Path(tempfile.mkdtemp())

        def page_with(n):
            urls = " ".join(f'"https://a0.muscache.com/im/pictures/miso/Hosting-{LID}/original/p{i:02d}.jpeg"'
                            for i in range(n))
            return {"html": urls, "sections": {"DESCRIPTION_DEFAULT": "desc"}, "reviews": [], "images": [],
                    "url": f"https://www.airbnb.com/rooms/{LID}"}

        def fake_fetch(url, dest, tries=3):
            Image.new("RGB", (64, 48), "red").save(dest, "JPEG")
            return True
        with mock.patch.object(listing_pull, "fetch", side_effect=fake_fetch):
            self.assertEqual(listing_pull.pull_url(f"https://www.airbnb.com/rooms/{LID}", out,
                                                   render=lambda u: page_with(10)), 0)
            self.assertEqual(len(list((out / "source" / "full").glob("*.jpg"))), 10)
            self.assertEqual(listing_pull.pull_url(f"https://www.airbnb.com/rooms/{LID}", out,
                                                   render=lambda u: page_with(8)), 0)
        self.assertEqual(sorted(p.name for p in (out / "source" / "full").glob("*.jpg")),
                         [f"{i:02d}.jpg" for i in range(1, 9)])
        self.assertEqual(len(list((out / "source" / "thumbs").glob("*.jpg"))), 8)
        self.assertFalse((out / "source" / "full.new").exists())

    def test_a_failed_pull_keeps_the_old_gallery(self):
        out = pathlib.Path(tempfile.mkdtemp())
        good = {"html": " ".join(f'"https://a0.muscache.com/im/pictures/miso/Hosting-{LID}/original/p{i:02d}.jpeg"'
                                 for i in range(9)),
                "sections": {}, "reviews": [], "images": [], "url": "u"}

        def ok_fetch(url, dest, tries=3):
            Image.new("RGB", (64, 48), "blue").save(dest, "JPEG")
            return True
        with mock.patch.object(listing_pull, "fetch", side_effect=ok_fetch):
            self.assertEqual(listing_pull.pull_url(f"https://www.airbnb.com/rooms/{LID}", out, render=lambda u: good), 0)
        with mock.patch.object(listing_pull, "fetch", return_value=False):
            self.assertEqual(listing_pull.pull_url(f"https://www.airbnb.com/rooms/{LID}", out, render=lambda u: good), 2)
        self.assertEqual(len(list((out / "source" / "full").glob("*.jpg"))), 9)
        self.assertFalse((out / "source" / "full.new").exists())


    def test_a_locked_old_gallery_is_a_plain_error_not_a_traceback(self):
        out = pathlib.Path(tempfile.mkdtemp())
        page = {"html": " ".join(f'"https://a0.muscache.com/im/pictures/miso/Hosting-{LID}/original/p{i:02d}.jpeg"'
                                 for i in range(9)), "sections": {}, "reviews": [], "images": [], "url": "u"}

        def ok_fetch(url, dest, tries=3):
            Image.new("RGB", (64, 48), "blue").save(dest, "JPEG")
            return True
        real_rmtree = listing_pull.shutil.rmtree

        def stuck_rmtree(path, ignore_errors=False):
            if pathlib.Path(path).name == "full":
                return            # Windows: a viewer holds the files, nothing is removed
            real_rmtree(path, ignore_errors=ignore_errors)
        with mock.patch.object(listing_pull, "fetch", side_effect=ok_fetch):
            self.assertEqual(listing_pull.pull_url(f"https://www.airbnb.com/rooms/{LID}", out, render=lambda u: page), 0)
            with mock.patch.object(listing_pull.shutil, "rmtree", side_effect=stuck_rmtree):
                self.assertEqual(listing_pull.pull_url(f"https://www.airbnb.com/rooms/{LID}", out,
                                                       render=lambda u: page), 2)
        self.assertEqual(len(list((out / "source" / "full").glob("*.jpg"))), 9)


if __name__ == "__main__":
    unittest.main()
