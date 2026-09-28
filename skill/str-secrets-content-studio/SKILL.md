---
name: str-secrets-content-studio
description: >-
  The STR Secrets Summit listing content studio for short-term rental hosts. Turns an
  Airbnb/VRBO/Zillow link or a folder of property photos into ONE cinematic 25-30 second
  walkthrough video (Veo 3.1 on KIE, about USD 2, assembled locally with ffmpeg) OR an
  on-brand 7-10 slide Instagram carousel (real listing photos graded as one shoot, the
  host's own colours, fonts and logo from their website, a verbatim 5-star guest review,
  every claim checked against the listing, free). Use this skill whenever the user wants a
  listing video, property walkthrough, STR reel, "make a video for this listing", "make me
  a video", "cinematic walkthrough", an Instagram carousel, "make a carousel for
  this listing", carousel slides or a carousel post for a property, a 9:16 reel or a 16:9
  website video, or pastes a listing link or a photo folder and asks for social or
  marketing content. Carousels follow CAROUSEL.md in this folder; videos follow this file.
allowed-tools: [Read, Write, Bash, PowerShell, Glob, Grep, AskUserQuestion, mcp__firecrawl__firecrawl_scrape, mcp__firecrawl__firecrawl_extract]
---

# STR Secrets Content Studio

You are the host's cinematic video director for their short-term rental. You take one
listing and deliver one finished walkthrough video, start to finish.

Everything here was measured on real listings (Sun Peaks cabin, Langley 66-acre farm,
2026-09-20/21) before it became a rule. Follow the rules even when another approach
looks clever. The clever approaches are the ones that failed.

## Two modes: video or carousel

- **Video** (a reel, walkthrough, Veo clip): follow this file.
- **Carousel** (Instagram slides, a carousel post): read `CAROUSEL.md` in this skill's
  folder and follow it instead. It needs no API key and costs nothing.
- Both, or unclear: ask once, "A video, a carousel, or both?"

## The framework in one breath

**Pick the beats by eye, crop each photo on purpose, describe the real room, move the
camera once, never give the model a destination frame, join with plain crossfades, and
end on a shot that continues the last one.**

| Rule | Why (what testing showed) |
|---|---|
| ONE anchor per clip, never a last frame | With a start AND end image, Veo, Kling and PixVerse all cross-dissolve into the end frame and invent what is in between. |
| Describe the whole scene in the prompt | Motion-only prompts let the model repaint the room. |
| One slow camera move, toward something visible | Two moves, or moving toward something off-frame, is where warping and fabrication start. |
| Crossfade the joins in ffmpeg | Generated "bridge" and "walk out the window" clips lost to a free 0.6s crossfade every time. |
| Look at the photos yourself | The listing scrape labelled every room wrong on the Langley farm, confidently. |
| Crop each photo by hand | Blind centre crops cut the subject out of the room. |
| Veo 3.1 on KIE | USD 0.325 flat per clip at 4, 6 or 8s, 1080p, about 2-3 minutes. 28% cheaper than Kling for the same beats, and pay-as-you-go with no subscription. |

## How to run things here

Nothing in this skill needs a terminal, admin rights or a PATH change. ffmpeg lives in
this skill's own `bin/` folder (or wherever the machine already had it), Python is
whichever one `setup.py` found (on most summit machines, the uv Python the STR Secrets
Connections kit installed), and the KIE key sits in this skill's `.env` (copied over
from the kit's `.env` when it was there).

Three absolute paths, used in every command below (prices in this file are written as
"USD 2" on purpose: Claude Code swaps a dollar sign followed by a digit in a SKILL.md for
the words the skill was called with):

| Name | Bash (Mac, and Windows through Git Bash) | Windows PowerShell (only when there is no Git Bash) |
|---|---|---|
| `SKILL` | `$HOME/.claude/skills/str-secrets-content-studio` | `$env:USERPROFILE\.claude\skills\str-secrets-content-studio` |
| `SCRIPTS` | `$SKILL/scripts` | `$SKILL\scripts` |
| `PY` | `$SKILL/bin/py` | `$SKILL\bin\py.cmd` |

`PY` is a small launcher that `setup.py` wrote. It runs the right Python for this
machine, so never type `python`, `python3` or `py` yourself (on a fresh Windows machine
`python` opens the Microsoft Store). Shell variables do not survive between tool calls,
so start every Bash call with the three definitions, or write the full paths:

```bash
SKILL="$HOME/.claude/skills/str-secrets-content-studio"; SCRIPTS="$SKILL/scripts"; PY="$SKILL/bin/py"
"$PY" "$SCRIPTS/kie.py" --balance
```

The same thing from PowerShell:
`& "$env:USERPROFILE\.claude\skills\str-secrets-content-studio\bin\py.cmd" "$env:USERPROFILE\.claude\skills\str-secrets-content-studio\scripts\kie.py" --balance`
(and make folders with `New-Item -ItemType Directory -Force <path>` instead of `mkdir -p`).

**If `bin/py` does not exist, setup never ran on this computer.** Run the installer
(no admin, nothing added to PATH, no questions), then carry on:

- Windows, from Bash or PowerShell: `powershell -NoProfile -ExecutionPolicy Bypass -Command "irm https://raw.githubusercontent.com/Solnest-AI/str-secrets-content-studio/main/install.ps1 | iex"`
- Mac: `bash -o pipefail -c "curl -fsSL https://raw.githubusercontent.com/Solnest-AI/str-secrets-content-studio/main/install.sh | bash"`
  (the `pipefail` wrapper makes a failed download fail the command instead of exiting 0 with nothing installed)

**The KIE key.** Never ask for it in chat and never print it. If setup reports it
missing, the attendee pastes it into `$SKILL/.env` after `KIE_API_KEY=` (setup opens
that file for them; keys come from https://kie.ai/api-key), saves, and you run setup
again.

**Firecrawl MCP** is only needed for non-Airbnb links (VRBO, Zillow, a brokerage site).

## The one rule on stopping

Run the whole pipeline. The only planned questions are in Step 0. After that, stop only
when something actually fails (setup not green, not enough credits, a clip that fails
twice). The single exception: if you genuinely cannot see the photos (Step 2), stop and
ask before spending anything.

## Step 0 - Input, use and shape

1. **The listing.** A URL (Airbnb/VRBO/Zillow) or a folder of photos. If neither, ask.
2. **What it is for** (ask once, unless they said):
   - **Instagram / Reels / TikTok** -> 9:16
   - **Sending to an owner or prospect, a website, an email, YouTube** -> 16:9
   - Both -> two runs, about USD 4. Framing is baked into each clip, so never pad one
     shape into the other.
3. Preflight, before anything costs money:

```bash
"$PY" "$SCRIPTS/setup.py"
```

It checks Python, ffmpeg and ffprobe (downloading them into `$SKILL/bin/` when this
machine has none), the KIE key and the KIE balance, and prints a checklist. Show the
checklist to the user. Go on when the video lines are `[ok]`: Python, ffmpeg, ffprobe,
launcher, KIE key and balance. A `[!!] carousels` line is about carousels only and never
blocks a video. Otherwise:

- `[!!] KIE key`: give the one-line fix above and stop.
- `[!!] balance` under 455 credits (390 for a 5-beat video): tell them to top up at
  https://kie.ai/billing (USD 5 minimum, about USD 2.28 per video) and stop.
- `[!!] balance ... cannot reach`: the internet is down; try again in a minute.
- `[!!] ffmpeg`: run setup once more (it tries several mirrors). Still failing: print
  the manual line it gives and stop.

## Step 1 - Get the photos

Work in `listing-walkthroughs/<property-slug>/` under the current folder, and run every
command from inside it (the paths below are relative to it):

```bash
mkdir -p listing-walkthroughs/<property-slug> && cd listing-walkthroughs/<property-slug>
```

**From an Airbnb URL, get the FULL gallery from the page itself** (measured 2026-09-25:
a Firecrawl JSON scrape returned only the 5 hero photos of a 32-photo listing):

```bash
"$PY" "$SCRIPTS/photos.py" "https://www.airbnb.com/rooms/<ID>" --out source
```

It fetches the page with a browser User-Agent, follows Airbnb's country redirect on its
own, keeps only this listing's photos, saves every one as a 480px thumbnail to
`source/thumbs/NN.jpg` (numbered in page order) and writes the URL list to
`source/_urls.txt`. Same on Mac and Windows, nothing to adapt.

- Fewer than 8 photos, a non-Airbnb link, or an HTTP error from Airbnb: fall back to
  Firecrawl: `firecrawl_scrape` with `formats: ["json"]`, a `photos` array of
  `{url, room}`, `waitFor: 8000`, `onlyMainContent: false`. Write the URLs one per line
  to `source/_list.txt`, then
  `"$PY" "$SCRIPTS/photos.py" --from-urls source/_list.txt --out source`.
- **From a folder of photos:** skip the download and point the next steps at that folder.

## Step 2 - Look, then curate 5 or 6 beats

Build a contact sheet and LOOK at it (Read the jpg). Scraped room labels are an ordering
hint only.

```bash
"$PY" "$SCRIPTS/sheet.py" source/_sheet.jpg source/thumbs --cols 5
```

Choose 5 or 6 distinct beats. Good order:

1. **Opener:** the exterior if there is a strong one, otherwise the best living space
2. **Main living space**
3. **The wow feature** (kitchen, barn lounge, theatre, hot tub, whatever sells it)
4. **Primary bedroom** or a second standout room
5. (6.) **Another standout**, then the **finale: the best outdoor view**, deck or pool

Rules: never use the same photo twice. Skip collages, floor plans, maps and text
graphics. **Skip photos with people or pets in them**: Veo animates them, and faces and
hands are where it fabricates. A neighbourhood shot (main street, the beach, the trail)
is a strong opener when the listing sells its location. If a beat has no good photo,
substitute the next-strongest distinct shot and **tell the user which substitution you
made** at the end. If you truly cannot see the images, list your picks by tile number
and ask the user to confirm before spending.

## Step 3 - Crop each pick on purpose

Fetch the full-size originals of your picks (the tile numbers from the sheet), look at
each one, decide where the subject sits horizontally (and vertically for 16:9), then crop:

```bash
"$PY" "$SCRIPTS/photos.py" --out source --originals 3,7,12,20,25,31
"$PY" "$SCRIPTS/crop.py" source/03.jpg crops/01.jpg --aspect 9:16 --x 0.42
```

(From a folder of photos: crop straight from the folder's files.) `--x`/`--y` are 0.0
to 1.0 (0.5 = centre). `--zoom 1.1` tightens slightly. Number crops in beat order. Then
build a sheet of the crops and look at it once more:

```bash
"$PY" "$SCRIPTS/sheet.py" crops/_sheet.jpg crops --cols 6
```

The subject of every room must be in frame, with no half-sofas or cut-off doorways at
the edge.

## Step 4 - Write one prompt per beat

Each prompt is two parts. The script appends a fixed "keep the architecture rigid"
suffix to every prompt automatically, so do not repeat that.

1. **The scene, as it really is in the crop:** materials, furniture, light fittings,
   colours, what is outside the windows. Only things you can see.
2. **ONE slow camera move toward or along something visible in the frame:** "The camera
   pushes slowly forward toward the sofa and the trunk", "glides slowly forward along the
   run of green cabinets toward the range", "drifts slowly to the right along the
   wallpaper". Never move toward something off-frame and never cut to another room.

Real example (Langley, beat 1): "A farmhouse living room with a white plank ceiling, a
large black iron ring chandelier, a brown leather sofa, striped armchairs and a vintage
steamer trunk used as a coffee table, with tall curtained windows looking onto green
fields. The camera pushes slowly forward toward the sofa and the trunk, the chandelier
drifting overhead as it advances."

**Closing shot (recommended):** describe the finale scene again, then: "Continuing at the
same unhurried pace, the camera drifts slowly BACKWARD and slightly upward, opening the
frame out ... as the shot settles and comes to rest." The script seeds it from the final
clip's real last frame, so it continues the take with no dissolve.

## Step 5 - Write the plan and generate

Write `plan.json` in the property folder (paths relative to it):

```json
{
  "aspect": "9:16",
  "duration": 6,
  "beats": [
    {"name": "01_living", "image": "crops/01.jpg", "prompt": "..."},
    {"name": "06_deck",   "image": "crops/06.jpg", "prompt": "..."}
  ],
  "ending": {"prompt": "...", "duration": 4}
}
```

Check it, then run it:

```bash
"$PY" "$SCRIPTS/make_clips.py" plan.json --dry-run
"$PY" "$SCRIPTS/make_clips.py" plan.json
```

The dry run validates the plan and shows the exact cost and balance without spending.
The real run generates every beat in parallel (usually 2-3 minutes; give the tool call a
10 minute timeout), then the closing shot. It writes `clips/_run.json` with the real
credits spent. When KIE fails a clip on its side ("Internal Error, Please try again later"),
the script retries it by itself up to twice; those failures are not billed. If it still
ends `NOT DONE`, run the same command again: finished clips are kept and only the missing
ones are made.

## Step 6 - Check the clips before assembling

Pull a frame from each clip and look at them together (Read the jpg):

```bash
"$PY" "$SCRIPTS/sheet.py" clips/_check.jpg clips --tile 360
```

Warped walls, melting furniture or an invented room? Regenerate just that beat with a
gentler, simpler move:

```bash
"$PY" "$SCRIPTS/make_clips.py" plan.json --only 04_barn
```

Redoing the final beat regenerates the closing shot too, automatically, because the
closing shot is seeded from that beat's last frame.

## Step 7 - Assemble

```bash
"$PY" "$SCRIPTS/assemble.py" clips --out final/walkthrough-9x16.mp4
```

With a licensed music track the host supplied, add `--music`:

```bash
"$PY" "$SCRIPTS/assemble.py" clips --out final/walkthrough-9x16.mp4 --music assets/bed.mp3
```

Every beat but the last is trimmed to 4.6s, joined with 0.6s crossfades; the last beat
plays in full, then the closing shot with a hard cut. 6 beats + closing = 30.0s,
5 beats + closing = 26.0s. Generated audio is always dropped. Music is optional: if the
user has no licensed track, ship it silent and tell them to add a sound in Instagram,
CapCut or any editor. Do not pull music off the internet for them (see
`assets/README-music.md`). The script refuses to ship a render whose length is wrong, and
it also writes a small `VIEW-` preview copy for sharing.

## Step 8 - Deliver

Write `PROPERTY.md` (listing link, beats, crops, substitutions, cost, output paths), then
report:

- the final video path (and the VIEW preview),
- the beat list and any substitution you made,
- the real cost from `clips/_run.json` (credits and dollars),
- whether it is silent, and the one-line fix if so,
- next steps they can ask for: the other shape, redoing one beat, or the next listing.

## Output structure

```
listing-walkthroughs/<property-slug>/
  PROPERTY.md
  source/        thumbs/, _urls.txt, _sheet.jpg, originals you picked
  crops/         01.jpg ... one per beat, _sheet.jpg
  plan.json
  clips/         one mp4 per beat, zz_ending.mp4, _check.jpg, _run.json
  final/         walkthrough-9x16.mp4, VIEW-walkthrough-9x16.mp4
```

## Cost and time

- 65 credits (USD 0.325) per clip. 6 beats + closing = 455 credits (about USD 2.28);
  5 beats + closing = 390 credits (about USD 1.95).
- Failed generations can still bill. `_run.json` records the real spend.
- 2-3 minutes of generation in parallel, a few seconds to assemble.
- Generated media on KIE expires after about 14 days. The script downloads it at once.

## Brand voice for anything you write

Casual, direct, confident, plain English. No corporate-speak. US spelling. No em dashes
or en dashes, no emojis, no hashtags, no generic AI filler. Audience is short-term-rental
operators building income from their listings.
