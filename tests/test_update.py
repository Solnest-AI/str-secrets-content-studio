"""scripts/update.py: installs only a published release into the skill folder, keeps the
user's .env, bin/ (ffmpeg) and their own files, and --undo puts the old version back.
Offline: releases are read from a local folder (CONTENT_STUDIO_RELEASE_DIR)."""
import io
import os
import pathlib
import sys
import tarfile
import tempfile
import unittest
from unittest import mock

SCRIPTS = pathlib.Path(__file__).resolve().parent.parent / "skill" / "str-secrets-content-studio" / "scripts"
sys.path.insert(0, str(SCRIPTS))

import update  # noqa: E402

FAKE_ENV = "KIE_API_KEY=kie_test_" + "0" * 24 + "\n"   # a made-up value, never a real key


def tarball(folder, version, files, top=None):
    """A GitHub-style source tarball: one top folder, the skill under skill/<name>/."""
    top = top or f"str-secrets-content-studio-{version}"
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        def add(rel, data):
            info = tarfile.TarInfo(f"{top}/{rel}")
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
        add("VERSION", f"{version}\n".encode())
        add("README.md", b"repo readme, not installed\n")
        for rel, text in files.items():
            add(f"skill/str-secrets-content-studio/{rel}", text.encode())
    (pathlib.Path(folder) / f"v{version}.tar.gz").write_bytes(buf.getvalue())


class UpdateTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        base = pathlib.Path(self.tmp.name)
        self.rel = base / "releases"
        self.rel.mkdir()
        self.root = base / "skills" / "str-secrets-content-studio"
        self.root.mkdir(parents=True)
        env = mock.patch.dict(os.environ, {update.LOCAL_RELEASES: str(self.rel)})
        env.start()
        self.addCleanup(env.stop)
        self.addCleanup(self.tmp.cleanup)
        old = {"SKILL.md": "old skill\n", "scripts/kie.py": "old kie\n", "scripts/dropped.py": "gone next\n"}
        tarball(self.rel, "1.0.0", old)
        for rel, text in old.items():
            (self.root / rel).parent.mkdir(parents=True, exist_ok=True)
            (self.root / rel).write_text(text, encoding="utf-8")
        (self.root / "VERSION").write_text("1.0.0\n", encoding="utf-8")
        (self.root / ".env").write_text(FAKE_ENV, encoding="utf-8")
        (self.root / "bin").mkdir()
        (self.root / "bin" / "ffmpeg").write_text("fake ffmpeg\n", encoding="utf-8")
        (self.root / "my-notes.md").write_text("mine\n", encoding="utf-8")

    def test_update_keeps_user_files_and_undo_goes_back(self):
        tarball(self.rel, "1.1.0", {"SKILL.md": "new skill\n", "scripts/kie.py": "new kie\n",
                                    "scripts/new.py": "brand new\n", "bin/ffmpeg": "release must not win\n",
                                    ".env": "KIE_API_KEY=from_release\n"})
        r = update.update(self.root)
        self.assertEqual(r["status"], "updated")
        self.assertEqual((self.root / "VERSION").read_text().strip(), "1.1.0")
        self.assertEqual((self.root / "SKILL.md").read_text(), "new skill\n")
        self.assertTrue((self.root / "scripts" / "new.py").is_file())
        self.assertFalse((self.root / "scripts" / "dropped.py").exists())   # shipped by 1.0.0, not 1.1.0
        self.assertFalse((self.root / "README.md").exists())                # repo files are not installed
        self.assertEqual((self.root / ".env").read_text(), FAKE_ENV)
        self.assertEqual((self.root / "bin" / "ffmpeg").read_text(), "fake ffmpeg\n")
        self.assertEqual((self.root / "my-notes.md").read_text(), "mine\n")
        self.assertEqual(update.update(self.root)["status"], "current")

        update.undo(self.root)
        self.assertEqual((self.root / "VERSION").read_text().strip(), "1.0.0")
        self.assertEqual((self.root / "SKILL.md").read_text(), "old skill\n")
        self.assertTrue((self.root / "scripts" / "dropped.py").is_file())
        self.assertFalse((self.root / "scripts" / "new.py").exists())
        self.assertEqual((self.root / ".env").read_text(), FAKE_ENV)
        self.assertEqual((self.root / "my-notes.md").read_text(), "mine\n")

    def test_refuses_a_git_checkout(self):
        (self.root.parent.parent / "skill").mkdir()
        clone_skill = self.root.parent.parent / "skill" / "str-secrets-content-studio"
        clone_skill.mkdir()
        (self.root.parent.parent / ".git").mkdir()
        tarball(self.rel, "1.1.0", {"SKILL.md": "new\n"})
        with self.assertRaises(update.UpdateError):
            update.update(clone_skill)

    def test_unsafe_release_changes_nothing(self):
        tarball(self.rel, "1.1.0", {"SKILL.md": "new\n"}, top="a")
        buf = io.BytesIO()
        with tarfile.open(fileobj=buf, mode="w:gz") as tar:
            for name in ("top/VERSION", "../evil"):
                info = tarfile.TarInfo(name)
                info.size = 1
                tar.addfile(info, io.BytesIO(b"x"))
        (self.rel / "v1.1.0.tar.gz").write_bytes(buf.getvalue())
        with self.assertRaises(update.UpdateError):
            update.update(self.root)
        self.assertEqual((self.root / "VERSION").read_text().strip(), "1.0.0")

    def test_no_release_yet_is_a_plain_error(self):
        for p in self.rel.glob("*"):
            p.unlink()
        with self.assertRaises(update.UpdateError):
            update.update(self.root)


if __name__ == "__main__":
    unittest.main()
