"""An earlier copy of this skill under another folder name is retired, not left next to it.

Two copies make the same videos and carousels and answer the same requests, so with both in
~/.claude/skills Claude could pick either (2026-09-28: the summit guide linked an earlier build
for a day before this skill had its own repo). A copy is recognized by its files, not its name.
Setup carries its KIE key over, then moves it to ~/.claude/skills-retired. Nothing is deleted,
and a symlinked developer checkout is moved as the link only."""
import os
import pathlib
import sys
import tempfile
import unittest
from unittest import mock

SCRIPTS = pathlib.Path(__file__).resolve().parent.parent / "skill" / "str-secrets-content-studio" / "scripts"
sys.path.insert(0, str(SCRIPTS))

import setup  # noqa: E402

FAKE_KEY = "kie_test_" + "0" * 24  # a made-up value, never a real key
EARLIER = "earlier-content-skill"   # the folder name does not matter, the files do


def make_copy(folder, key=FAKE_KEY):
    for f in setup.COPY_FINGERPRINT:
        (folder / f).parent.mkdir(parents=True, exist_ok=True)
        (folder / f).write_text("x\n", encoding="utf-8")
    if key is not None:
        (folder / ".env").write_text(f"KIE_API_KEY={key}\n", encoding="utf-8")
    return folder


class RetireEarlierCopies(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.home = pathlib.Path(self.tmp.name)
        self.skills = self.home / ".claude" / "skills"
        self.skills.mkdir(parents=True)
        self.env = self.skills / setup.SKILL_DIR.name / ".env"
        self.env.parent.mkdir()
        env = dict(os.environ)
        env.pop("STUDIO_KEEP_COPIES", None)
        self.environ = mock.patch.dict(os.environ, env, clear=True)
        self.environ.start()

    def tearDown(self):
        self.environ.stop()
        self.tmp.cleanup()

    def run_it(self):
        return setup.retire_earlier_copies(self.skills, self.env, stamp="20260928-120000")

    def test_nothing_installed_does_nothing(self):
        self.assertEqual(self.run_it(), [])
        self.assertFalse((self.home / ".claude" / "skills-retired").exists())

    def test_moves_an_earlier_copy_out_and_carries_the_key(self):
        make_copy(self.skills / EARLIER)
        [r] = self.run_it()
        dest = self.home / ".claude" / "skills-retired" / f"{EARLIER}-20260928-120000"
        self.assertEqual(r["moved_to"], dest)
        self.assertTrue(r["key_carried"])
        self.assertFalse((self.skills / EARLIER).exists())
        self.assertTrue((dest / "SKILL.md").is_file())          # moved, not deleted
        self.assertTrue((dest / ".env").is_file())              # its key file goes with it
        self.assertIn(f"KIE_API_KEY={FAKE_KEY}", self.env.read_text(encoding="utf-8"))

    def test_other_skills_and_this_skill_are_never_touched(self):
        other = self.skills / "carousel-creator"                # a different skill: SKILL.md only
        other.mkdir()
        (other / "SKILL.md").write_text("x\n", encoding="utf-8")
        partial = self.skills / "half-a-copy"                   # some of the files, not all
        make_copy(partial)
        (partial / "scripts" / "make_clips.py").unlink()
        make_copy(self.env.parent, key=None)                    # this skill itself
        self.assertEqual(self.run_it(), [])
        for d in (other, partial, self.env.parent):
            self.assertTrue(d.is_dir())

    def test_an_existing_key_is_never_overwritten(self):
        make_copy(self.skills / EARLIER)
        self.env.write_text("KIE_API_KEY=mine\n", encoding="utf-8")
        [r] = self.run_it()
        self.assertFalse(r["key_carried"])
        self.assertEqual(self.env.read_text(encoding="utf-8"), "KIE_API_KEY=mine\n")
        self.assertIsNotNone(r["moved_to"])

    def test_a_copy_without_a_key_is_still_moved(self):
        make_copy(self.skills / EARLIER, key=None)
        [r] = self.run_it()
        self.assertFalse(r["key_carried"])
        self.assertIsNotNone(r["moved_to"])
        self.assertFalse(self.env.exists())

    @unittest.skipIf(os.name == "nt", "creating symlinks on Windows needs developer mode")
    def test_a_symlinked_checkout_moves_as_the_link_only(self):
        checkout = make_copy(self.home / "dev" / "checkout")
        (self.skills / EARLIER).symlink_to(checkout, target_is_directory=True)
        [r] = self.run_it()
        self.assertTrue(r["was_link"])
        self.assertTrue(r["moved_to"].is_symlink())
        self.assertEqual(os.readlink(r["moved_to"]), str(checkout))
        for f in setup.COPY_FINGERPRINT + (".env",):            # the checkout is untouched
            self.assertTrue((checkout / f).is_file(), f)
        self.assertTrue(r["key_carried"])

    def test_keep_switch_leaves_it_but_still_carries_the_key(self):
        make_copy(self.skills / EARLIER)
        with mock.patch.dict(os.environ, {"STUDIO_KEEP_COPIES": "1"}):
            [r] = self.run_it()
        self.assertIsNone(r["moved_to"])
        self.assertIn("STUDIO_KEEP_COPIES", r["error"])
        self.assertTrue((self.skills / EARLIER).is_dir())
        self.assertTrue(r["key_carried"])

    def test_a_failed_move_is_reported_not_raised(self):
        make_copy(self.skills / EARLIER)
        with mock.patch.object(setup.os, "rename", side_effect=PermissionError(13, "Permission denied")):
            [r] = self.run_it()
        self.assertIsNone(r["moved_to"])
        self.assertIn("could not move it", r["error"])
        self.assertTrue((self.skills / EARLIER).is_dir())

    def test_a_second_run_finds_nothing_left_to_do(self):
        make_copy(self.skills / EARLIER)
        self.run_it()
        self.assertEqual(self.run_it(), [])

    def test_the_real_earlier_build_matches_the_fingerprint(self):
        # this skill's own files ARE the fingerprint: every earlier build shipped the same scripts
        for f in setup.COPY_FINGERPRINT:
            self.assertTrue((setup.SKILL_DIR / f).is_file(), f)


if __name__ == "__main__":
    unittest.main()
