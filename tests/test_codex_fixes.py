"""Regression tests for the Codex review of 2026-09-28: money and silent-failure guards.
Offline: no network, no credits (KIE is mocked). Run: python3 -m unittest discover -s tests -v
"""
import io
import json
import pathlib
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from unittest import mock

SCRIPTS = pathlib.Path(__file__).resolve().parent.parent / "skill" / "str-secrets-content-studio" / "scripts"
sys.path.insert(0, str(SCRIPTS))

import assemble  # noqa: E402
import kie  # noqa: E402
import make_clips  # noqa: E402
import photos  # noqa: E402

FAKE_MP4 = b"\x00\x00\x00\x18ftypisom" + b"\x00" * 30000
FAKE_JPG = b"\xff\xd8\xff\xe0" + b"\x00" * 5000


class _Resp:
    """A urlopen() stand-in that streams one body."""
    def __init__(self, data):
        self.data = data

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def read(self, n=-1):
        d, self.data = self.data, b""
        return d


class DownloadsAreChecked(unittest.TestCase):
    def test_html_error_page_is_never_kept_as_a_clip(self):
        with tempfile.TemporaryDirectory() as t:
            dest = pathlib.Path(t) / "clip.mp4"
            with mock.patch("urllib.request.urlopen",
                            side_effect=lambda *a, **k: _Resp(b"<html>" + b"x" * 30000)) as uo, \
                 mock.patch.object(kie.time, "sleep"):
                with self.assertRaises(kie.KieError) as cm:
                    kie.download("http://x/y.mp4", dest, kind="video")
            self.assertIn("not a video", str(cm.exception))
            self.assertEqual(uo.call_count, 3)          # the download is retried, never a task
            self.assertFalse(dest.exists())
            self.assertEqual(list(pathlib.Path(t).iterdir()), [])     # no .part left behind

    def test_truncated_download_is_rejected(self):
        with tempfile.TemporaryDirectory() as t:
            dest = pathlib.Path(t) / "clip.mp4"
            with mock.patch("urllib.request.urlopen", side_effect=lambda *a, **k: _Resp(FAKE_MP4[:500])), \
                 mock.patch.object(kie.time, "sleep"):
                with self.assertRaises(kie.KieError) as cm:
                    kie.download("http://x/y.mp4", dest, kind="video")
            self.assertIn("only 500 bytes", str(cm.exception))
            self.assertFalse(dest.exists())

    def test_real_media_lands_in_place(self):
        with tempfile.TemporaryDirectory() as t:
            dest = pathlib.Path(t) / "sub" / "clip.mp4"
            with mock.patch("urllib.request.urlopen", return_value=_Resp(FAKE_MP4)):
                self.assertEqual(kie.download("http://x/y.mp4", dest, kind="video"), len(FAKE_MP4))
            self.assertTrue(dest.is_file())
            img = pathlib.Path(t) / "fix.png"
            with mock.patch("urllib.request.urlopen", return_value=_Resp(FAKE_JPG)):
                kie.download("http://x/y.png", img, kind="image")
            self.assertTrue(img.is_file())


class OnePaidTaskPerClip(unittest.TestCase):
    def test_create_task_is_never_retried(self):
        calls = []

        def boom(path, body=None, timeout=120):
            calls.append(path)
            raise kie.KieError("cannot reach KIE at api.kie.ai (timed out)")
        with mock.patch.object(kie, "call", side_effect=boom):
            with self.assertRaises(kie.KieError):
                kie.create_task({"model": "x"})
        self.assertEqual(calls, ["/jobs/createTask"])

    def test_a_failed_download_does_not_create_a_second_task(self):
        with tempfile.TemporaryDirectory() as t:
            with mock.patch.object(kie, "create_task", return_value="T1") as ct, \
                 mock.patch.object(kie, "wait_task", return_value=(
                     "success", {"resultJson": json.dumps({"resultUrls": ["u"]})})), \
                 mock.patch.object(kie, "download", side_effect=kie.KieError("download failed after 3 tries")):
                r = kie.veo_clip("img", "p" * 80, pathlib.Path(t) / "c.mp4", duration=6, aspect="9:16")
        self.assertFalse(r["ok"])
        self.assertEqual(r["task"], "T1")
        self.assertEqual(ct.call_count, 1)

    def test_resuming_a_task_creates_nothing(self):
        with tempfile.TemporaryDirectory() as t:
            dest = pathlib.Path(t) / "c.mp4"

            def fake_download(url, d, kind="video", tries=3):
                pathlib.Path(d).write_bytes(FAKE_MP4)
                return len(FAKE_MP4)
            with mock.patch.object(kie, "create_task") as ct, \
                 mock.patch.object(kie, "wait_task", return_value=(
                     "success", {"resultJson": json.dumps({"resultUrls": ["u"]})})), \
                 mock.patch.object(kie, "download", side_effect=fake_download):
                r = kie.veo_clip(None, "p" * 80, dest, duration=6, aspect="9:16", task_id="T9")
        self.assertTrue(r["ok"])
        self.assertTrue(r["resumed"])
        self.assertEqual(ct.call_count, 0)

    def test_polling_survives_network_hiccups_and_returns_the_fail_state(self):
        answers = [kie.KieError("cannot reach KIE at api.kie.ai (x)"),
                   {"data": {"state": "generating"}},
                   {"data": {"state": "fail", "failMsg": "content policy"}}]

        def fake_call(path, body=None, timeout=120):
            a = answers.pop(0)
            if isinstance(a, Exception):
                raise a
            return a
        with mock.patch.object(kie, "call", side_effect=fake_call), mock.patch.object(kie.time, "sleep"):
            state, rec = kie.wait_task("T1", max_wait=60)
        self.assertEqual(state, "fail")
        self.assertEqual(rec["failMsg"], "content policy")

    def test_a_bad_key_while_polling_is_raised_not_retried(self):
        with mock.patch.object(kie, "call", side_effect=kie.KieError("KIE code=401 msg=bad")), \
             mock.patch.object(kie.time, "sleep"):
            with self.assertRaises(kie.KieError):
                kie.wait_task("T1", max_wait=60)


class KieShapes(unittest.TestCase):
    def test_credits_accepts_a_number_or_a_dict_and_rejects_the_rest(self):
        with mock.patch.object(kie, "call", return_value={"code": 200, "data": 123}):
            self.assertEqual(kie.credits(), 123.0)
        with mock.patch.object(kie, "call", return_value={"code": 200, "data": {"credits": "45.5"}}):
            self.assertEqual(kie.credits(), 45.5)
        with mock.patch.object(kie, "call", return_value={"code": 200, "data": {"foo": 1}}):
            with self.assertRaises(kie.KieError):
                kie.credits()

    def test_extract_urls_never_raises_on_odd_shapes(self):
        self.assertEqual(kie.extract_urls({"resultJson": "{not json"}), [])
        self.assertEqual(kie.extract_urls({"resultJson": json.dumps([1, 2])}), [])
        self.assertEqual(kie.extract_urls({"resultJson": {"resultUrls": "not-a-list"}}), [])
        self.assertEqual(kie.extract_urls("garbage"), [])


class ResumeInsteadOfPayingTwice(unittest.TestCase):
    def _plan(self, tmp):
        d = pathlib.Path(tmp)
        (d / "crops").mkdir()
        (d / "crops" / "a.jpg").write_bytes(FAKE_JPG)
        (d / "crops" / "b.jpg").write_bytes(FAKE_JPG + b"b")
        (d / "plan.json").write_text(json.dumps({"aspect": "9:16", "duration": 6, "beats": [
            {"name": "01_a", "image": "crops/a.jpg", "prompt": "A" * 80},
            {"name": "02_b", "image": "crops/b.jpg", "prompt": "B" * 80}]}))
        return d

    def test_classify(self):
        clip = pathlib.Path("nope.mp4")
        self.assertEqual(make_clips.classify("x", None, "fp", clip, False), "new")
        self.assertEqual(make_clips.classify("x", {"ok": True, "fingerprint": "old"}, "fp", clip, False), "new")
        self.assertEqual(make_clips.classify("x", {"task": "T", "state": "error", "fingerprint": "fp"},
                                             "fp", clip, False), "resume")
        self.assertEqual(make_clips.classify("x", {"task": "T", "state": "fail", "fingerprint": "fp"},
                                             "fp", clip, False), "new")
        self.assertEqual(make_clips.classify("x", {"ok": True, "fingerprint": "fp"}, "fp", clip, True), "new")

    def test_interrupted_run_keeps_the_paid_clip_and_resumes_the_other(self):
        with tempfile.TemporaryDirectory() as t:
            d = self._plan(t)
            _, base, aspect, dur, beats, _ = make_clips.load_plan(d / "plan.json")
            clips = d / "clips"
            clips.mkdir()
            (clips / "01_a.mp4").write_bytes(FAKE_MP4)
            fp_a = make_clips.beat_fingerprint(beats[0], dur, aspect)
            fp_b = make_clips.beat_fingerprint(beats[1], dur, aspect)
            (clips / "_run.json").write_text(json.dumps({"results": {
                "01_a": {"ok": True, "task": "TA", "fingerprint": fp_a},
                "02_b": {"ok": False, "task": "TB", "state": "error", "fingerprint": fp_b,
                         "error": "cannot reach"}}}))
            seen = []

            def fake_veo(url, prompt, dest, **kw):
                seen.append((url, kw.get("task_id")))
                pathlib.Path(dest).write_bytes(FAKE_MP4)
                return {"ok": True, "task": kw.get("task_id") or "NEW", "state": "success",
                        "resumed": bool(kw.get("task_id")), "seconds": 1.0, "bytes": 1, "file": str(dest)}
            buf = io.StringIO()
            with mock.patch.object(make_clips, "credits", side_effect=[1000.0, 1000.0]), \
                 mock.patch.object(make_clips, "find_key", return_value=("k", "env")), \
                 mock.patch.object(make_clips, "upload", return_value="http://img") as up, \
                 mock.patch.object(make_clips, "veo_clip", side_effect=fake_veo), \
                 mock.patch.object(make_clips, "probe", return_value={"w": 1080, "h": 1920, "secs": 6.0}), \
                 redirect_stdout(buf):
                rc = make_clips.main([str(d / "plan.json")])
            self.assertEqual(rc, 0, buf.getvalue())
            self.assertEqual(seen, [(None, "TB")])          # 01_a kept, 02_b resumed, nothing new
            self.assertEqual(up.call_count, 0)
            state = json.loads((clips / "_run.json").read_text())
            self.assertTrue(state["results"]["02_b"]["ok"])
            self.assertEqual(state["results"]["01_a"]["task"], "TA")
            self.assertIn("0 new Veo generation(s) = 0 credits", buf.getvalue())

    def test_dry_run_counts_only_new_tasks(self):
        with tempfile.TemporaryDirectory() as t:
            d = self._plan(t)
            _, base, aspect, dur, beats, _ = make_clips.load_plan(d / "plan.json")
            clips = d / "clips"
            clips.mkdir()
            (clips / "01_a.mp4").write_bytes(FAKE_MP4)
            (clips / "_run.json").write_text(json.dumps({"results": {
                "01_a": {"ok": True, "task": "TA",
                         "fingerprint": make_clips.beat_fingerprint(beats[0], dur, aspect)}}}))
            buf = io.StringIO()
            with mock.patch.object(make_clips, "credits", return_value=1000.0), \
                 mock.patch.object(make_clips, "find_key", return_value=("k", "env")), redirect_stdout(buf):
                rc = make_clips.main([str(d / "plan.json"), "--dry-run"])
            self.assertEqual(rc, 0)
            self.assertIn("KEEP   01_a", buf.getvalue())
            self.assertIn("1 new Veo generation(s) = 65 credits", buf.getvalue())

    def test_only_forces_a_fresh_generation(self):
        with tempfile.TemporaryDirectory() as t:
            d = self._plan(t)
            _, base, aspect, dur, beats, _ = make_clips.load_plan(d / "plan.json")
            clips = d / "clips"
            clips.mkdir()
            (clips / "01_a.mp4").write_bytes(FAKE_MP4)
            (clips / "_run.json").write_text(json.dumps({"results": {
                "01_a": {"ok": True, "task": "TA",
                         "fingerprint": make_clips.beat_fingerprint(beats[0], dur, aspect)}}}))
            buf = io.StringIO()
            with mock.patch.object(make_clips, "credits", return_value=1000.0), \
                 mock.patch.object(make_clips, "find_key", return_value=("k", "env")), redirect_stdout(buf):
                make_clips.main([str(d / "plan.json"), "--dry-run", "--only", "01_a"])
            self.assertIn("1 new Veo generation(s) = 65 credits", buf.getvalue())
            self.assertNotIn("KEEP", buf.getvalue())

    def test_changed_prompt_means_a_new_generation(self):
        with tempfile.TemporaryDirectory() as t:
            d = self._plan(t)
            _, base, aspect, dur, beats, _ = make_clips.load_plan(d / "plan.json")
            fp = make_clips.beat_fingerprint(beats[0], dur, aspect)
            beats[0]["prompt"] = "C" * 80
            self.assertNotEqual(fp, make_clips.beat_fingerprint(beats[0], dur, aspect))


class AssembleRefusesHalfDoneWork(unittest.TestCase):
    def _clips(self, t, ending_ok):
        c = pathlib.Path(t) / "clips"
        c.mkdir()
        (c / "01_a.mp4").write_bytes(FAKE_MP4)
        if ending_ok:
            (c / "zz_ending.mp4").write_bytes(FAKE_MP4)
        (c / "_run.json").write_text(json.dumps({
            "aspect": "9:16", "order": ["01_a"], "ending": "zz_ending",
            "results": {"01_a": {"ok": True}, "zz_ending": {"ok": ending_ok, "error": "x"}}}))
        return c

    def test_missing_closing_shot_is_an_error_unless_asked_for(self):
        with tempfile.TemporaryDirectory() as t:
            c = self._clips(t, ending_ok=False)
            buf = io.StringIO()
            with redirect_stdout(buf):
                rc = assemble.main([str(c), "--out", str(pathlib.Path(t) / "out.mp4")])
            self.assertEqual(rc, 1)
            self.assertIn("closing shot", buf.getvalue())
            self.assertIn("--without-ending", buf.getvalue())

    def test_stale_clip_is_caught_against_plan_json(self):
        with tempfile.TemporaryDirectory() as t:
            d = pathlib.Path(t)
            (d / "crops").mkdir()
            (d / "crops" / "a.jpg").write_bytes(FAKE_JPG)
            (d / "plan.json").write_text(json.dumps({"aspect": "9:16", "duration": 6, "beats": [
                {"name": "01_a", "image": "crops/a.jpg", "prompt": "A" * 80}]}))
            c = d / "clips"
            c.mkdir()
            self.assertEqual(assemble.stale_clips(c, ["01_a"], {"01_a": {"ok": True, "fingerprint": "old"}}),
                             ["01_a"])
            _, _, aspect, dur, beats, _ = make_clips.load_plan(d / "plan.json")
            good = make_clips.beat_fingerprint(beats[0], dur, aspect)
            self.assertEqual(assemble.stale_clips(c, ["01_a"], {"01_a": {"ok": True, "fingerprint": good}}), [])
            self.assertEqual(assemble.stale_clips(c, ["01_a"], {"01_a": {"ok": True}}), [])   # old runs


class RerunsDoNotMixListings(unittest.TestCase):
    def test_numbered_files_from_the_last_pull_are_cleared(self):
        with tempfile.TemporaryDirectory() as t:
            d = pathlib.Path(t)
            for n in ("01.jpg", "02.jpg", "17.webp", "_sheet.jpg", "notes.txt"):
                (d / n).write_bytes(b"x")
            self.assertEqual(photos.clear_numbered(d), 3)
            self.assertEqual(sorted(p.name for p in d.iterdir()), ["_sheet.jpg", "notes.txt"])
            self.assertEqual(photos.clear_numbered(d / "missing"), 0)


class DocsRunAsWritten(unittest.TestCase):
    """Commands Claude copies must not carry literal [optional] brackets."""
    def test_no_bracketed_optional_arguments_in_commands(self):
        root = SCRIPTS.parent
        for name in ("SKILL.md", "CAROUSEL.md"):
            text = (root / name).read_text(encoding="utf-8")
            in_block = False
            for n, line in enumerate(text.splitlines(), 1):
                if line.startswith("```"):
                    in_block = not in_block
                    continue
                if in_block and ("[--" in line):
                    self.fail(f"{name}:{n} has a bracketed option in a command block: {line.strip()}")


if __name__ == "__main__":
    unittest.main()
