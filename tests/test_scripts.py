"""Offline tests for the Cinematic Director scripts. No network, no credits.
Run:  python3 -m unittest discover -s tests -v
"""
import gzip
import io
import json
import os
import pathlib
import sys
import tempfile
import unittest
import urllib.error
import zipfile
from unittest import mock

SCRIPTS = pathlib.Path(__file__).resolve().parent.parent / "skill" / "str-secrets-content-studio" / "scripts"
sys.path.insert(0, str(SCRIPTS))

import assemble  # noqa: E402
import crop  # noqa: E402
import kie  # noqa: E402
import make_clips  # noqa: E402
import media  # noqa: E402
import photos  # noqa: E402
import setup  # noqa: E402
import sheet  # noqa: E402


class CropBox(unittest.TestCase):
    def test_landscape_to_vertical_is_height_bound_and_even(self):
        cw, ch, cx, cy = crop.crop_box(2560, 1706, "9:16")
        self.assertEqual(ch, 1706)
        self.assertEqual(cw % 2, 0)
        self.assertAlmostEqual(cw / ch, 9 / 16, places=2)
        self.assertEqual(cy, 0)

    def test_x_is_clamped_inside_the_photo(self):
        cw, _, cx, _ = crop.crop_box(2560, 1706, "9:16", x=0.0)
        self.assertEqual(cx, 0)
        cw, _, cx, _ = crop.crop_box(2560, 1706, "9:16", x=1.0)
        self.assertEqual(cx, 2560 - cw)

    def test_zoom_tightens(self):
        a = crop.crop_box(2560, 1706, "9:16")
        b = crop.crop_box(2560, 1706, "9:16", zoom=1.25)
        self.assertLess(b[0], a[0])

    def test_creates_the_output_folder(self):
        # SKILL.md crops into crops/01.jpg on a fresh property folder; ffmpeg will not
        # create crops/ itself, so a first run failed until crop.py made it.
        with tempfile.TemporaryDirectory() as t:
            dst = pathlib.Path(t) / "crops" / "01.jpg"
            seen = []
            with mock.patch.object(crop, "probe", return_value={"w": 2560, "h": 1706}), \
                    mock.patch.object(crop, "tool", return_value="ffmpeg"), \
                    mock.patch.object(crop, "run", side_effect=lambda cmd: seen.append(dst.parent.is_dir())), \
                    mock.patch("sys.stdout", new=io.StringIO()):
                self.assertEqual(crop.main(["in.jpg", str(dst), "--aspect", "9:16"]), 0)
            self.assertEqual(seen, [True])


class Timeline(unittest.TestCase):
    def test_langley_recipe_is_exactly_30s(self):
        used, offsets, total = assemble.timeline([6.0] * 6, 4.6, 0.6, ending_secs=4.0)
        self.assertEqual(used, [4.6] * 5 + [6.0])
        self.assertAlmostEqual(total, 30.0, places=3)
        self.assertAlmostEqual(offsets[0], 4.0, places=3)
        self.assertAlmostEqual(offsets[-1], 20.0, places=3)

    def test_five_beats_with_ending_is_26s(self):
        _, _, total = assemble.timeline([6.0] * 5, 4.6, 0.6, ending_secs=4.0)
        self.assertAlmostEqual(total, 26.0, places=3)

    def test_short_clip_is_not_trimmed_longer_than_it_is(self):
        used, _, _ = assemble.timeline([4.0, 6.0], 4.6, 0.6)
        self.assertEqual(used, [4.0, 6.0])

    def test_single_beat(self):
        used, offsets, total = assemble.timeline([6.0], 4.6, 0.6)
        self.assertEqual((used, offsets, total), ([6.0], [], 6.0))


class Plan(unittest.TestCase):
    def _plan(self, tmp, **over):
        d = pathlib.Path(tmp)
        (d / "a.jpg").write_bytes(b"x")
        (d / "b.jpg").write_bytes(b"x")
        p = {"aspect": "9:16", "duration": 6, "beats": [
            {"name": "01_living", "image": "a.jpg", "prompt": "L" * 80},
            {"name": "02_deck", "image": "b.jpg", "prompt": "D" * 80}]}
        p.update(over)
        (d / "plan.json").write_text(json.dumps(p))
        return d / "plan.json"

    def test_valid_plan_loads(self):
        with tempfile.TemporaryDirectory() as t:
            plan, base, aspect, dur, beats, ending = make_clips.load_plan(self._plan(t))
            self.assertEqual((aspect, dur, len(beats), ending), ("9:16", 6, 2, None))

    def test_rejects_bad_duration_aspect_and_reused_photo(self):
        with tempfile.TemporaryDirectory() as t:
            bad = self._plan(t, duration=5, aspect="4:3", beats=[
                {"name": "a", "image": "a.jpg", "prompt": "x" * 80},
                {"name": "b", "image": "a.jpg", "prompt": "x" * 80}])
            with self.assertRaises(ValueError) as cm:
                make_clips.load_plan(bad)
            msg = str(cm.exception)
            self.assertIn("duration", msg)
            self.assertIn("aspect", msg)
            self.assertIn("same photo", msg)

    def test_rejects_thin_prompt_and_missing_image(self):
        with tempfile.TemporaryDirectory() as t:
            bad = self._plan(t, beats=[{"name": "a", "image": "nope.jpg", "prompt": "push in"}])
            with self.assertRaises(ValueError) as cm:
                make_clips.load_plan(bad)
            self.assertIn("image not found", str(cm.exception))
            self.assertIn("prompt too short", str(cm.exception))

    def test_hold_suffix_keeps_architecture_rigid(self):
        self.assertIn("never warp", make_clips.HOLD)


class Redo(unittest.TestCase):
    BEATS = [{"name": "01_living"}, {"name": "04_barn"}, {"name": "06_deck"}]
    ENDING = {"prompt": "x" * 80}

    def test_no_only_means_every_beat_and_the_ending(self):
        todo, do_end, note = make_clips.select_work(self.BEATS, self.ENDING, set())
        self.assertEqual(len(todo), 3)
        self.assertTrue(do_end)
        self.assertEqual(note, "")

    def test_redoing_a_middle_beat_leaves_the_ending_alone(self):
        todo, do_end, note = make_clips.select_work(self.BEATS, self.ENDING, {"04_barn"})
        self.assertEqual([b["name"] for b in todo], ["04_barn"])
        self.assertFalse(do_end)

    def test_redoing_the_final_beat_redoes_the_closing_shot(self):
        todo, do_end, note = make_clips.select_work(self.BEATS, self.ENDING, {"06_deck"})
        self.assertEqual([b["name"] for b in todo], ["06_deck"])
        self.assertTrue(do_end)
        self.assertIn("closing shot", note)

    def test_ending_alone(self):
        todo, do_end, _ = make_clips.select_work(self.BEATS, self.ENDING, {"ending"})
        self.assertEqual(todo, [])
        self.assertTrue(do_end)


class KeyLookup(unittest.TestCase):
    def test_env_var_wins_and_key_is_never_in_the_source_label(self):
        with mock.patch.dict(os.environ, {"KIE_API_KEY": "sk-test-123"}):
            key, where = kie.find_key()
        self.assertEqual(key, "sk-test-123")
        self.assertNotIn("sk-test", where)

    def test_missing_key_explains_where_to_put_it(self):
        with mock.patch.dict(os.environ, {}, clear=True), \
             mock.patch.object(kie, "key_search_paths", return_value=[pathlib.Path("/nonexistent/.env")]):
            with self.assertRaises(kie.KieError) as cm:
                kie.find_key()
        self.assertIn("KIE_API_KEY=", str(cm.exception))

    def test_kit_key_is_found_through_the_claude_json_pointer(self):
        with tempfile.TemporaryDirectory() as t:
            home = pathlib.Path(t)
            kit_env = home / "somewhere" / "kit" / ".env"
            kit_env.parent.mkdir(parents=True)
            kit_env.write_text("KIE_API_KEY=kit-key-1\n")
            (home / ".claude.json").write_text(json.dumps(
                {"mcpServers": {"kie": {"type": "stdio", "env": {"KIE_ENV_PATH": str(kit_env)}}}}))
            with mock.patch.object(pathlib.Path, "home", return_value=home), \
                 mock.patch.object(pathlib.Path, "cwd", return_value=home / "nowhere"), \
                 mock.patch.object(kie, "SKILL_DIR", home / "skill"), \
                 mock.patch.dict(os.environ, {}, clear=True):
                key, where = kie.find_key()
        self.assertEqual(key, "kit-key-1")
        self.assertNotIn("kit-key", where)

    def test_kit_folder_on_the_desktop_is_found_without_a_pointer(self):
        with tempfile.TemporaryDirectory() as t:
            home = pathlib.Path(t)
            kit = home / "Desktop" / "str-secrets-connections-main"
            kit.mkdir(parents=True)
            (kit / ".env").write_text("HOSPITABLE_API_KEY=abc\nKIE_API_KEY=kit-key-2\n")
            with mock.patch.object(pathlib.Path, "home", return_value=home), \
                 mock.patch.object(pathlib.Path, "cwd", return_value=home / "nowhere"), \
                 mock.patch.object(kie, "SKILL_DIR", home / "skill"), \
                 mock.patch.dict(os.environ, {}, clear=True):
                key, where = kie.find_key()
        self.assertEqual(key, "kit-key-2")
        self.assertIn("str-secrets-connections", where)

    def test_http_200_with_error_code_is_a_failure(self):
        fake = mock.MagicMock()
        fake.__enter__.return_value.read.return_value = json.dumps(
            {"code": 401, "msg": "invalid key"}).encode()
        with mock.patch.object(kie, "headers", return_value={}), \
             mock.patch("urllib.request.urlopen", return_value=fake):
            with self.assertRaises(kie.KieError) as cm:
                kie.call("/chat/credit")
        self.assertIn("401", str(cm.exception))

    def test_no_internet_is_a_plain_message_not_a_traceback(self):
        with mock.patch.object(kie, "headers", return_value={}), \
             mock.patch("urllib.request.urlopen", side_effect=urllib.error.URLError("dns down")):
            with self.assertRaises(kie.KieError) as cm:
                kie.call("/chat/credit")
        self.assertIn("cannot reach", str(cm.exception))

    def test_html_instead_of_json_is_a_plain_message(self):
        fake = mock.MagicMock()
        fake.__enter__.return_value.read.return_value = b"<html>502 Bad Gateway</html>"
        with mock.patch.object(kie, "headers", return_value={}), \
             mock.patch("urllib.request.urlopen", return_value=fake):
            with self.assertRaises(kie.KieError) as cm:
                kie.call("/chat/credit")
        self.assertIn("not JSON", str(cm.exception))

    def test_result_url_shapes(self):
        self.assertEqual(kie.extract_urls({"resultJson": json.dumps({"resultUrls": ["a"]})}), ["a"])
        self.assertEqual(kie.extract_urls({"resultJson": {"data": {"origin_urls": ["b"]}}}), ["b"])
        self.assertEqual(kie.extract_urls({}), [])

    def test_veo_rejects_unsupported_duration(self):
        with self.assertRaises(kie.KieError):
            kie.veo_clip("u", "p", "/tmp/x.mp4", duration=5)


class ToolLookup(unittest.TestCase):
    def test_the_skills_own_bin_wins_over_path(self):
        with tempfile.TemporaryDirectory() as t:
            fake = pathlib.Path(t) / f"ffmpeg{media.EXE}"
            fake.write_bytes(b"#!/bin/sh\n")
            fake.chmod(0o755)
            with mock.patch.object(media, "BIN_DIR", pathlib.Path(t)), \
                 mock.patch.dict(media._CACHE, {}, clear=True):
                self.assertEqual(media.tool("ffmpeg"), str(fake))

    def test_missing_tool_points_at_setup(self):
        with mock.patch.object(media, "candidates", return_value=iter([])), \
             mock.patch.dict(media._CACHE, {}, clear=True):
            with self.assertRaises(media.MediaError) as cm:
                media.tool("ffprobe")
        self.assertIn("setup.py", str(cm.exception))


class Photos(unittest.TestCase):
    PAGE = ("<html>"
            "https:\\u002F\\u002Fa0.muscache.com\\u002Fim\\u002Fpictures\\u002Fmiso\\u002FHosting-777\\u002Foriginal\\u002Fa1.jpeg?im_w=720 "
            '"https://a0.muscache.com/im/pictures/miso/Hosting-777/original/a1.jpeg" '
            "https://a0.muscache.com/im/pictures/miso/Hosting-777/original/b2.jpg "
            "https://a0.muscache.com/im/pictures/user/User-1/original/face.jpeg "
            "https://a0.muscache.com/im/pictures/miso/Hosting-999/original/other.jpeg"
            "</html>")

    def test_extract_unescapes_dedupes_and_keeps_only_this_listing(self):
        urls, own = photos.extract_photo_urls(self.PAGE, "777")
        self.assertTrue(own)
        self.assertEqual(urls, [
            "https://a0.muscache.com/im/pictures/miso/Hosting-777/original/a1.jpeg",
            "https://a0.muscache.com/im/pictures/miso/Hosting-777/original/b2.jpg"])

    def test_older_listing_without_hosting_ids_returns_everything_but_avatars(self):
        page = ("https://a0.muscache.com/im/pictures/11111111-2222.jpg "
                "https://a0.muscache.com/im/pictures/user/User-1/original/face.jpeg")
        urls, own = photos.extract_photo_urls(page, "777")
        self.assertFalse(own)
        self.assertEqual(urls, ["https://a0.muscache.com/im/pictures/11111111-2222.jpg"])

    def test_listing_id_from_the_usual_link_shapes(self):
        self.assertEqual(photos.listing_id("https://www.airbnb.ca/rooms/12345?adults=2"), "12345")
        self.assertEqual(photos.listing_id("https://www.airbnb.com/rooms/plus/67?x=1"), "67")
        self.assertIsNone(photos.listing_id("https://www.vrbo.com/1234"))

    def test_sized_only_uses_widths_airbnb_serves(self):
        u = "https://a0.muscache.com/im/pictures/miso/Hosting-1/original/a.jpeg"
        self.assertEqual(photos.sized(u + "?im_w=720", 2560), u + "?im_w=2560")
        self.assertEqual(photos.sized("https://images.example.com/x.jpg", 480),
                         "https://images.example.com/x.jpg")
        with self.assertRaises(ValueError):
            photos.sized(u, 400)

    # The real thing, captured 2026-09-28: a POST form, no link anywhere in it.
    SWITCH = ('<!DOCTYPE html><html><head><meta charset="utf-8"><title>Redirecting to www.airbnb.ca'
              '</title></head><body onload="document.forms[0].submit()"><form method="POST" '
              'action="https://www.airbnb.ca/v2/domain_switch/handoff"><input type="hidden" '
              'name="payload" value="eyJ..."></form></body></html>')

    def test_country_switch_form_is_followed_to_the_local_domain(self):
        big = "<html>" + "x" * 30000 + "</html>"
        calls = []

        def fake_fetch(url, timeout=45):
            calls.append(url)
            return url, (self.SWITCH if "airbnb.com" in url else big)
        with mock.patch.object(photos, "fetch", side_effect=fake_fetch):
            final, body = photos.fetch_listing("https://www.airbnb.com/rooms/555?locale=en")
        self.assertEqual(calls, ["https://www.airbnb.com/rooms/555?locale=en",
                                 "https://www.airbnb.ca/rooms/555?locale=en"])
        self.assertEqual(body, big)

    def test_meta_refresh_redirect_is_followed_too(self):
        tiny = ('<html><head><meta http-equiv="refresh" content="0; url=https://www.airbnb.ca/rooms/555?x=1">'
                "</head></html>")
        self.assertEqual(photos.redirect_target(tiny, "555"), "https://www.airbnb.ca/rooms/555?x=1")
        self.assertIsNone(photos.redirect_target("<html>" + "x" * 30000, "555"))

    def test_redirect_loop_is_an_error_not_a_hang(self):
        with mock.patch.object(photos, "fetch", side_effect=lambda u, timeout=45: (u, self.SWITCH)):
            with self.assertRaises(photos.PhotosError) as cm:
                photos.fetch_listing("https://www.airbnb.ca/rooms/555")
        self.assertIn("redirecting", str(cm.exception))

    def test_numbering_and_extensions(self):
        self.assertEqual(photos.numbered(3, 32), "03")
        self.assertEqual(photos.numbered(3, 120), "003")
        self.assertEqual(photos.ext_of("https://x/a.JPEG?im_w=480"), ".jpg")
        self.assertEqual(photos.ext_of("https://x/a.webp"), ".webp")


class Sheet(unittest.TestCase):
    def test_folders_and_globs_are_expanded_and_underscore_files_skipped(self):
        with tempfile.TemporaryDirectory() as t:
            d = pathlib.Path(t)
            for n in ("b.jpg", "a.jpg", "_sheet.jpg", "notes.txt", "c.mp4"):
                (d / n).write_bytes(b"x")
            self.assertEqual([p.name for p in sheet.expand_inputs([str(d)])],
                             ["a.jpg", "b.jpg", "c.mp4"])
            self.assertEqual([p.name for p in sheet.expand_inputs([str(d / "*.jpg")])],
                             ["_sheet.jpg", "a.jpg", "b.jpg"])
            self.assertEqual([p.name for p in sheet.expand_inputs([str(d / "a.jpg")])], ["a.jpg"])


class Setup(unittest.TestCase):
    def test_every_platform_has_download_sources(self):
        for key in (("Windows", "x64"), ("Windows", "arm64"), ("Darwin", "arm64"),
                    ("Darwin", "x64"), ("Linux", "x64"), ("Linux", "arm64")):
            self.assertTrue(setup.sources_for(*key), key)
            for _, parts in setup.sources_for(*key):
                for part in parts:
                    self.assertTrue(part["url"].startswith("https://"))

    def test_harvest_finds_binaries_in_nested_zip_and_in_a_gz(self):
        with tempfile.TemporaryDirectory() as t:
            d = pathlib.Path(t)
            z = d / "ff.zip"
            with zipfile.ZipFile(z, "w") as zf:
                zf.writestr(f"ffmpeg-9.0-essentials_build/bin/ffmpeg{media.EXE}", b"MZfake")
                zf.writestr(f"ffmpeg-9.0-essentials_build/bin/ffprobe{media.EXE}", b"MZfake")
                zf.writestr("ffmpeg-9.0-essentials_build/doc/ffmpeg.html", b"<html>")
            self.assertEqual(sorted(setup.harvest(z, d / "bin")), ["ffmpeg", "ffprobe"])
            self.assertEqual((d / "bin" / f"ffmpeg{media.EXE}").read_bytes(), b"MZfake")
            g = d / "ffprobe-x.gz"
            with gzip.open(g, "wb") as f:
                f.write(b"ELFfake")
            self.assertEqual(setup.harvest(g, d / "bin2", gz_name="ffprobe"), ["ffprobe"])
            self.assertEqual((d / "bin2" / f"ffprobe{media.EXE}").read_bytes(), b"ELFfake")

    def test_launchers_point_at_this_python_and_use_lf(self):
        with tempfile.TemporaryDirectory() as t:
            with mock.patch.object(setup, "BIN_DIR", pathlib.Path(t)):
                sh, cmd = setup.write_launchers()
            raw = sh.read_bytes()
            self.assertTrue(raw.startswith(b"#!/bin/sh\n"))
            self.assertNotIn(b"\r", raw)
            self.assertIn(setup.python_for_launcher().as_posix().encode(), raw)
            self.assertIn(b"exit /b", cmd.read_bytes())

    def test_env_write_keeps_other_lines_and_the_key_is_not_printed(self):
        with tempfile.TemporaryDirectory() as t:
            p = pathlib.Path(t) / ".env"
            p.write_text("# hello\nFOO=1\nKIE_API_KEY=\n")
            setup.write_env(p, "abc123")
            self.assertEqual(p.read_text(), "# hello\nFOO=1\nKIE_API_KEY=abc123\n")
            setup.write_env(p, "")
            self.assertIn("KIE_API_KEY=\n", p.read_text())
            fresh = pathlib.Path(t) / "new.env"
            setup.write_env(fresh, "k")
            self.assertIn("KIE_API_KEY=k", fresh.read_text())
            self.assertIn("kie.ai/api-key", fresh.read_text())

    def test_ensure_key_copies_the_kit_key_into_the_skill_env(self):
        with tempfile.TemporaryDirectory() as t:
            home = pathlib.Path(t)
            skill = home / "skill"
            skill.mkdir()
            kit_env = home / "Documents" / "str-secrets-connections" / ".env"
            kit_env.parent.mkdir(parents=True)
            kit_env.write_text("KIE_API_KEY=from-the-kit\n")
            with mock.patch.object(pathlib.Path, "home", return_value=home), \
                 mock.patch.object(pathlib.Path, "cwd", return_value=home / "nowhere"), \
                 mock.patch.object(kie, "SKILL_DIR", skill), \
                 mock.patch.object(setup, "SKILL_DIR", skill), \
                 mock.patch.dict(os.environ, {}, clear=True):
                ok, text = setup.ensure_key(open_editor=False)
                self.assertTrue(ok)
                self.assertIn("copied", text)
                self.assertNotIn("from-the-kit", text)
                self.assertIn("KIE_API_KEY=from-the-kit", (skill / ".env").read_text())
                ok2, text2 = setup.ensure_key(open_editor=False)
                self.assertTrue(ok2)
                self.assertNotIn("copied", text2)

    def test_ensure_key_creates_a_blank_env_when_nothing_is_found(self):
        with tempfile.TemporaryDirectory() as t:
            home = pathlib.Path(t)
            skill = home / "skill"
            skill.mkdir()
            with mock.patch.object(pathlib.Path, "home", return_value=home), \
                 mock.patch.object(pathlib.Path, "cwd", return_value=home / "nowhere"), \
                 mock.patch.object(kie, "SKILL_DIR", skill), \
                 mock.patch.object(setup, "SKILL_DIR", skill), \
                 mock.patch.dict(os.environ, {}, clear=True):
                ok, text = setup.ensure_key(open_editor=False)
            self.assertFalse(ok)
            self.assertIn("kie.ai/api-key", text)
            self.assertIn("KIE_API_KEY=\n", (skill / ".env").read_text())


class AsciiOnlyOutput(unittest.TestCase):
    """Windows consoles crash on non-ASCII prints (found in the Listing Optimizer)."""
    def test_scripts_print_ascii_only(self):
        for f in SCRIPTS.glob("*.py"):
            for n, line in enumerate(f.read_text(encoding="utf-8").splitlines(), 1):
                if "print(" in line:
                    self.assertTrue(line.isascii(), f"{f.name}:{n} prints non-ASCII")

    def test_installers_and_docs_are_ascii(self):
        root = SCRIPTS.parent.parent.parent
        for name in ("install.ps1", "install.sh", "INSTALL.md"):
            text = (root / name).read_text(encoding="utf-8")
            self.assertTrue(text.isascii(), f"{name} has non-ASCII characters")
            self.assertNotIn("\r", text, f"{name} has CRLF line endings")


if __name__ == "__main__":
    unittest.main()
