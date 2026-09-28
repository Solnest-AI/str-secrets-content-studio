"""Offline tests for photo_fix.py (no network, no credits: kie is mocked).
Run:  python3 -m unittest discover -s tests -v
"""
import io
import pathlib
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from unittest import mock

SCRIPTS = pathlib.Path(__file__).resolve().parent.parent / "skill" / "str-secrets-content-studio" / "scripts"
sys.path.insert(0, str(SCRIPTS))

try:
    from PIL import Image
    HAVE_PIL = True
except ImportError:  # pragma: no cover
    HAVE_PIL = False
if HAVE_PIL:
    import photo_fix  # noqa: E402


@unittest.skipUnless(HAVE_PIL, "Pillow not installed")
class PhotoFix(unittest.TestCase):
    def test_closest_aspect_never_reframes_much(self):
        self.assertEqual(photo_fix.closest_aspect(2560, 1920), "4:3")
        self.assertEqual(photo_fix.closest_aspect(1920, 2560), "3:4")
        self.assertEqual(photo_fix.closest_aspect(2560, 1706), "3:2")
        self.assertEqual(photo_fix.closest_aspect(1000, 1000), "1:1")

    def photos(self, n=2):
        d = pathlib.Path(tempfile.mkdtemp())
        ps = []
        for i in range(n):
            p = d / f"{i + 1:02d}.jpg"
            Image.new("RGB", (400, 300), "white").save(p)
            ps.append(str(p))
        return d, ps

    def test_dry_run_shows_cost_and_spends_nothing(self):
        d, ps = self.photos(2)
        with mock.patch.object(photo_fix.kie, "credits", return_value=500.0), \
                mock.patch.object(photo_fix.kie, "call") as call, redirect_stdout(io.StringIO()) as buf:
            rc = photo_fix.main(ps + ["--out", str(d / "fixed"), "--dry-run"])
        self.assertEqual(rc, 0)
        call.assert_not_called()
        self.assertIn("28 credits", buf.getvalue())

    def test_not_enough_credits_stops_before_spending(self):
        d, ps = self.photos(2)
        with mock.patch.object(photo_fix.kie, "credits", return_value=20.0), \
                mock.patch.object(photo_fix.kie, "call") as call, redirect_stdout(io.StringIO()) as buf:
            rc = photo_fix.main(ps + ["--out", str(d / "fixed")])
        self.assertEqual(rc, 2)
        call.assert_not_called()
        self.assertIn("not enough", buf.getvalue())

    def test_night_prompt_only_on_named_photos(self):
        self.assertIn("dusk", photo_fix.prompt_for(True))
        self.assertNotIn("dusk", photo_fix.prompt_for(False))
        self.assertIn("Do not add, remove, move", photo_fix.prompt_for(False))


if __name__ == "__main__":
    unittest.main()
