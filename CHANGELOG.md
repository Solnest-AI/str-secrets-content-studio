# Changelog

## 1.0.2 (2026-09-28)

- One content skill, not two. If an earlier copy of this skill is installed under another
  folder name (the summit guide linked an earlier build for a day), setup now carries its
  KIE key over and moves it from `~/.claude/skills` to `~/.claude/skills-retired`, so
  Claude never has two skills answering "make a carousel for this listing". A copy is
  recognized by its files, not its name; other skills are never touched. Nothing is deleted:
  setup prints the one move that undoes it. A symlinked developer checkout is moved as the
  link only. `STUDIO_KEEP_COPIES=1` leaves such a copy where it is.

## 1.0.1 (2026-09-28)

Money and silent-failure fixes from a Codex review of the whole skill (same code as the
Solnest Cinematic Director 2.1.2).

- One paid Veo task per clip, ever. A failed poll or download is retried against the same
  task; a second task is only created when Claude asks for a redo with `--only`.
- `clips/_run.json` is saved after every clip with its KIE task id, so an interrupted run
  resumes: finished clips are kept, a created-but-unfinished task is polled again, and only
  what is missing is generated. A clip is regenerated when its photo, prompt, length or
  shape changed (fingerprint per clip); `assemble.py` refuses clips that no longer match
  `plan.json`.
- Every KIE download lands in a `.part` file and must be real media of the right size and
  kind before it replaces anything (no more HTML error pages saved as clips or photos).
- `credits()` and `extract_urls()` tolerate KIE's other answer shapes instead of crashing.
- `assemble.py` no longer ships a shorter video when the closing shot failed; `--without-ending`
  says so on purpose.
- Listing pulls download into a staging folder and swap it in, so a rerun never keeps an
  earlier listing's photos; `photos.py` clears numbered files the same way.
- `listing_pull.py` accepts older Airbnb photo URLs (no `Hosting-<id>`) with a warning.
- Docs: no literal `[--option]` brackets in commands, a PowerShell form for `"$UV" run`,
  the Mac install line wrapped in `bash -o pipefail` so a failed download cannot exit 0,
  and the video preflight only needs the video lines green.

## 1.0.0 (2026-09-28)

The STR Secrets Summit 2.0 Content Studio, its own skill (`str-secrets-content-studio`),
installed into its own folder. Paste this repo's link into Claude Code and say "set this up".

- **Carousels (free):** a listing link becomes an on-brand 8 or 9 slide Instagram carousel
  in the host's own colours, fonts and logo. Every word and number is checked against the
  listing, the review slide quotes a real 5-star review word for word, every label fits on
  one line, every text line passes a contrast check, and the cover must be crisp (a soft
  cover gets the optional 7-cent sharpen offered first).
- **Videos (about USD 2.28 in KIE credits):** a 25 to 30 second cinematic walkthrough, one
  real photo per shot, crossfades, a closing shot that continues the last one.
- **Setup:** no terminal, no admin. It checks and installs what it needs (Python through uv,
  ffmpeg, a headless browser), picks up the KIE key from the STR Secrets connections kit,
  shows a green check, then offers to make the first carousel or video in the same chat.
  Mac and Windows.
