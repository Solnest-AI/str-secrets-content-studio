# Install the STR Secrets Content Studio

Claude: the person pasted a link to this file into Claude Code. Follow it exactly, one
step per message. You run every command yourself with your Bash tool (Windows without
Git Bash: your PowerShell tool). The attendee never opens a terminal. Never ask for an
API key in the chat, and never print one.

## 1. Run the installer for this computer

Tell them in one line what is about to happen ("installing the Content Studio, about a
minute, nothing for you to do"), then run the line for their OS:

**Windows** (works from Bash and from PowerShell):

```
powershell -NoProfile -ExecutionPolicy Bypass -Command "irm https://raw.githubusercontent.com/Solnest-AI/str-secrets-content-studio/main/install.ps1 | iex"
```

**Mac:**

```
bash -o pipefail -c "curl -fsSL https://raw.githubusercontent.com/Solnest-AI/str-secrets-content-studio/main/install.sh | bash"
```

(`pipefail` makes a failed download fail the command; a bare `curl | bash` exits 0 with
nothing installed when the download fails.)

It puts the skill in `~/.claude/skills/str-secrets-content-studio`, finds Python (or
installs one through uv, the way the STR Secrets Connections kit does), downloads ffmpeg
into the skill's own folder if the machine has none, picks up the KIE key from the
Connections kit if it is there, checks the KIE balance, sets up the carousel tools (uv, a
headless browser, about 200 MB once), and ends with a checklist. No
admin rights, nothing added to PATH, no questions. One to three minutes on the first run.
Use a generous tool timeout (15 minutes): the ffmpeg download is 30 to 90 MB and the
headless browser about 200 MB.

Show the attendee the checklist it printed.

## 2. Read the checklist

- Every line `[ok]` (the `balance` line may say `[!!]`): done. Carry on with steps 4 and 5
  of the README's "set this up" section: the green check line, then offer to make their first
  carousel or video right here, from their Airbnb link. No restart needed.
- `[!!] KIE key`: the installer created the `.env` file and opened it for them. They get
  a key at https://kie.ai/api-key (sign in with Google, Create New Key, no IP whitelist),
  paste it after `KIE_API_KEY=` in that file, save, and tell you "saved". Then run the
  step 1 line again. Do not ask for the key in the chat.
- `[!!] balance` under 455 credits: one video costs about $2.28 (455 credits). They top up
  at https://kie.ai/billing ($5 minimum). Not a blocker for the install; say it once.
- `[!!] ffmpeg`: the download failed, usually the network. Run step 1 once more (it tries
  several mirrors). If it fails again: Windows `winget install --id Gyan.FFmpeg -e`, Mac
  `brew install ffmpeg`, then quit and reopen Claude Code and run step 1 again.
- `[!!] carousels`: the headless browser or its Python packages did not finish
  downloading, usually the network. Run step 1 once more. Videos are not affected.
- `ERROR: no working Python`: run step 1 once more; if it repeats, send the full output to
  Ryan (ryan.lefebvre@strsecrets.com).

## 3. Update or repair later

Run the step 1 line again. It replaces the skill's scripts with the latest version and
keeps the `.env` and the downloaded ffmpeg.
