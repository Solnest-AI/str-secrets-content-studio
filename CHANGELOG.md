# Changelog

## 1.1.3 (2026-09-29)

- `--get` keeps one copy of identical creatives. A dynamic ad lists every size of the same
  picture (Austin: 16 images, 14 byte-identical); now 3 files to look at instead of 16.
  Found in a three-market run (Austin, Myrtle Beach, Breckenridge).

## 1.1.2 (2026-09-29)

- Ad Spy's competitor judgment is back where str-ad-spy had it: Claude reads every ad's copy
  and drops software, coaches, cleaners, photographers, lenders, other-city ads and anything
  off-topic, then labels each owner-facing or guest-facing, before ranking by copies. The
  script's keyword marks are only a first pass. New in the drop list: developers and realtors
  selling units, which ranked first on copy count in Miami and Nashville.

## 1.1.1 (2026-09-28)

From a live test on Miami, Scottsdale and Gatlinburg, then one real clone:
- Dynamic ads (Meta fills `{{product.brand}}` per viewer) now show their real card copy, or
  say they are dynamic, instead of the placeholder.
- Spanish-language managers ("Administramos tu propiedad...") and listing-quality ads
  ("Your listing is the only thing a guest sees...") count as competitors.
- Verified end to end: a Cabins For You "Revenue Reset" ad from the Gatlinburg search
  cloned for another brand, text letter-perfect first try, 6 credits.

## 1.1.0 (2026-09-28)

Ad Spy joins the Content Studio (ADS.md): find the Facebook and Instagram ads STR operators
run in a market, break the best ones down, and clone a static ad or a carousel for your brand.

- `ad_spy.py` reads Meta's public Ad Library page through Firecrawl (the Connections kit's
  key). Tested side by side on Nashville against Meta's own Ad Library search: same
  advertisers, but only the page gives each ad's full copy, call to action, link, images and
  video files, start date and how many copies are running. A market search runs the phrase
  ladder from the str-ad-spy research (33 ads from 21 advertisers in Nashville vs 14 from
  Meta's search), ignores national queries, collapses duplicate creatives into a copy count,
  and marks software, courses and off-topic ads as not competitors. `--get` downloads the
  picks with their copy. Meta's own search stays as the fallback without a Firecrawl key.
- ADS.md: the framework for each pick (hook, angle, offer, audience, format, proof, a
  fill-in-the-blank formula, what to steal), then clone or new ideas.
- `ad_make.py` clones a static ad or a carousel card with GPT Image 2 on KIE (about 3 cents
  an image): the competitor's ad as the layout blueprint, the host's real listing photo as
  the hero, the host's own words. Never their claims, photos or logo. Dry run, balance check,
  one task per image, KIE-side failures retried unbilled, finished images kept on a rerun.
  Images only: no video ads, no generated people.
- Setup shows an `ad spy` line (Firecrawl key found or not); it never blocks videos or carousels.

## 1.0.4 (2026-09-28)

- A listing re-pull on Windows while a photo from the old pull is open (a viewer, File
  Explorer's preview) now stops with a plain message and keeps the old photos, instead of a
  traceback. Found in a final review pass.

## 1.0.3 (2026-09-28)

- KIE's own failures retry themselves. A clip KIE fails on its side ("Internal Error,
  Please try again later") is retried with a fresh task up to twice inside the same run;
  those failures are not billed (measured 2026-09-28 on Windows: 14 of 20 Veo tasks failed
  that way, 0 credits taken, the finished video cost exactly 7 x 65). Timeouts and download
  errors are still resumed on the next run, never retried with a new task.

## 1.0.2 (2026-09-28)

- A soft carousel cover is a note, not a stop. Typical Airbnb galleries score 37-53 against
  the crispness bar of 80, so the gate fired on nearly every first try. The check now prints
  the note, the slide renders (sharpened harder), and Claude offers the 7-cent photo fix
  after the host has seen the preview. `soft_ok` is still accepted and only silences the note.

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
