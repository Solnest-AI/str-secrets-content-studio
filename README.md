# STR Secrets Content Studio (Claude Code)

Paste a listing link into Claude Code. Get back an on-brand **Instagram carousel** of the
property (free), or a 25 to 30 second **cinematic walkthrough video** (about $2 in KIE
credits). Everything runs on your own computer. You never type a command.

Built by Ryan Lefebvre / **Solnest AI**. Free to use.

---

## Claude: someone pasted this link and said "set this up"

Do exactly this, one step per message. You run every command yourself with your Bash tool
(Windows without Git Bash: your PowerShell tool). The person never opens a terminal and
never types a command. Never ask for an API key in the chat, and never print one.

1. Tell them in one line: "Setting up the STR Secrets Content Studio: a few minutes,
   nothing for you to do."
2. Run the installer for their computer, with a 15 minute tool timeout (the first run
   downloads ffmpeg and a headless browser):
   - **Windows** (from Bash or PowerShell):
     `powershell -NoProfile -ExecutionPolicy Bypass -Command "irm https://raw.githubusercontent.com/Solnest-AI/str-secrets-content-studio/main/install.ps1 | iex"`
   - **Mac:**
     `bash -o pipefail -c "curl -fsSL https://raw.githubusercontent.com/Solnest-AI/str-secrets-content-studio/main/install.sh | bash"`
3. Show them the checklist it printed, then read it:
   - **`[!!] KIE key`:** videos need it; carousels do not. If they only want a carousel
     today, go on to step 4 and come back to the key before any video. Otherwise setup is
     not finished until the key is in. The installer created a
     `.env` file and opened it. They get a key at https://kie.ai/api-key (sign in with
     Google, Create New Key), paste it after `KIE_API_KEY=`, save, and tell you "saved".
     Run step 2 again.
   - **`[!!] carousels` or `[!!] ffmpeg`:** usually the network. Run step 2 once more.
   - **`ERROR: no working Python`:** run step 2 once more. If it repeats, send the full
     output to Ryan (ryan.lefebvre@strsecrets.com).
   - **Every other line `[ok]`** (the `balance` line may say `[!!]`): setup is done. Go on.
4. Say: "✅ **STR Secrets Content Studio is set up.**" If the `balance` line said `[!!]`,
   add: "Carousels are free. A video needs about 455 Kie credits (USD 2.28): top up USD 5
   at https://kie.ai/billing before you make one." Then ask: **"Want to make your first one
   now? Paste the link to one of your Airbnb listings and tell me: a carousel or a video?"**
5. When they answer, make it right here in this chat. No restart: read the instructions
   from the installed skill with your Read tool and follow them from the top, as if the
   skill had been called:
   - **Carousel:** `~/.claude/skills/str-secrets-content-studio/CAROUSEL.md`
   - **Video:** `~/.claude/skills/str-secrets-content-studio/SKILL.md`

   (Windows: the same files under `%USERPROFILE%\.claude\skills\str-secrets-content-studio\`.)
   A video with the balance under 455 credits: ask them to top up first, and offer the
   carousel while they do. From the next time they open Claude Code, the skill loads on
   its own: they just say "make me a carousel for ..." or "make me a video for ...".

To update or repair later, run step 2 again: it keeps the `.env` and the downloaded ffmpeg.
Full detail: [INSTALL.md](INSTALL.md).

---

### What you need

| Thing | What it does | Cost |
|---|---|---|
| **KIE API key** ([kie.ai](https://kie.ai/api-key)) | Generates the video clips (carousels need no key) | Pay as you go, $5 minimum, about $2 per video |
| **ffmpeg** | Joins the clips on your machine | Free. Downloaded for you |
| **Python 3.9+** and **uv** | Run the helper scripts (carousels also use Pillow and Playwright, which uv fetches) | Free. Found or installed for you |
| Headless browser (carousels) | Reads the listing and your site, renders the slides | Free. Installed for you (about 200 MB once) |
| Firecrawl MCP (optional) | Reads non-Airbnb listing pages | Free plan is fine |

Your KIE key lives in a file called `.env` inside the skill folder, one line:
`KIE_API_KEY=your_key`. If you set up the STR Secrets Connections kit, the installer
copies it from there. **Never paste a key into the chat.**

---

## Use it

```
make me a video for https://www.airbnb.com/rooms/...
```

It asks what the video is for (Instagram = vertical 9:16, owner or website = 16:9), then:

1. pulls every photo from the listing,
2. looks at them and picks 5 or 6 beats (it does not trust the listing's room labels),
3. crops each photo on purpose,
4. writes one prompt per beat describing the real room plus one slow camera move,
5. shows you the cost, then generates the clips in parallel (2 to 3 minutes),
6. adds a closing shot that continues the last clip seamlessly,
7. stitches everything into one MP4 in `listing-walkthroughs/<property>/final/`.

### Carousels

```
make me a carousel for https://www.airbnb.com/rooms/...
```

It asks for your website (for your colours, fonts and logo) and your call to action once,
then pulls every photo, the listing text and the guest reviews, plans 8 or 9 slides (the
thing that sets you apart, amenities, details, bedrooms, a real 5-star guest quote,
location, your closing line), checks every word and number against your listing before it
renders anything, and shows you a preview and the caption. Your photos are never AI-edited
unless you ask. Free: nothing is generated.

## The recipe, and why

Every rule came from a failed test first.

- **One anchor per clip.** Give an AI video model a start AND an end photo and it
  dissolves into the end photo and invents what is in between. We saw it on Veo, Kling
  and PixVerse. One start frame per clip, always.
- **Describe the real room.** Motion-only prompts let the model repaint the space.
- **One slow camera move toward something in the frame.** More moves is where walls
  start to bend.
- **Plain crossfades between beats.** Generated "transition" clips lost to a free 0.6
  second crossfade every time.
- **Look at the photos.** On one farm listing the scraped room labels were all wrong.
- **Veo 3.1 on KIE.** $0.325 flat per clip, 1080p, and 28% cheaper than Kling for the
  same shots.

## What it costs

| Video | Credits | Dollars |
|---|---|---|
| 6 beats + closing shot (30s) | 455 | about $2.28 |
| 5 beats + closing shot (26s) | 390 | about $1.95 |
| Redo one bad beat | 65 | $0.33 |

Both shapes (vertical and wide) means two runs. The framing is baked into each clip.

## Music

None ships with it. A music track in a public repo is a licensing call that belongs to
you. Add your own licensed track with `--music`, or post the silent cut and pick a sound
in Instagram. Details in
[assets/README-music.md](skill/str-secrets-content-studio/assets/README-music.md).

---

## How the install works (for the curious)

- `install.ps1` (Windows) and `install.sh` (Mac/Linux) copy `skill/str-secrets-content-studio`
  into `~/.claude/skills/`, find a Python 3.9+ (a real one, never the Microsoft Store stub;
  on a Mac never the Xcode stub), or install one through [uv](https://astral.sh/uv), then
  hand over to `scripts/setup.py`.
- `setup.py` reuses ffmpeg if the machine has it, otherwise downloads it into the skill's
  `bin/` folder from the first mirror that works (gyan.dev, BtbN and ffmpeg-static on
  GitHub for Windows; ffmpeg-static on GitHub and martin-riedl.de for Mac, Apple Silicon
  and Intel). It writes a launcher, `bin/py`, so every command in the skill runs through
  the same Python on every machine. It looks for the KIE key in the skill's `.env`, in the
  environment, and in the STR Secrets Connections kit (through the `kie` server registered
  in `~/.claude.json`, or the kit folder on the Desktop, Documents or Downloads), and copies
  it into the skill's `.env`. Then it checks the balance: 455 credits is one video.
- For carousels, `setup.py` installs [uv](https://astral.sh/uv) if it is missing (per user,
  no admin), writes `bin/uv` so the skill never depends on PATH, and runs
  `scripts/doctor.py` through it once. uv fetches Pillow and Playwright (pinned in each
  script's header) into its own cache, and doctor.py downloads the headless browser
  (about 200 MB, once). If that step fails, videos still work and the checklist says so.
- Nothing is installed system-wide and nothing needs admin rights.

## Update

Paste this repo link into Claude Code again and say "update this". Claude reruns the
installer, which replaces the scripts and keeps your `.env`, ffmpeg and the headless browser.

## For developers

```bash
uv run --no-project --with pillow --with playwright==1.60.0 python -m unittest discover -s tests -v
./install.sh                                  # install from this clone (Windows: .\install.ps1)
```

The tests are offline: no network, no credits. Without Pillow the carousel tests skip.
The video scripts are Python standard library plus ffmpeg; the carousel scripts run
through uv. All of them print ASCII only so they cannot crash a Windows console.

---

*Free from **Solnest AI**. We help business owners put AI to work so they can work on the
business, not in it. [solnestai.com](https://solnestai.com) |
IG [@Ryan_Le5](https://instagram.com/Ryan_Le5) + [@SolnestAi](https://instagram.com/SolnestAi)*
