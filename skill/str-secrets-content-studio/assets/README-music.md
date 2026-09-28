# Music

No music ships with this skill, on purpose.

Redistributing a music track inside a public repo is a licensing decision, and it is
yours to make, not the skill's. A silent master plus 60 seconds in CapCut is a better
default than an accidental copyright claim on a client's listing video.

## To add a bed

Drop an audio file in this folder and point the stitcher at it:

    python3 scripts/assemble.py clips --out final/walkthrough-9x16.mp4 \
      --music assets/bed.mp3

It is looped if it is shorter than the video and trimmed if longer, with a 1s fade in,
a 2.5s fade out, and volume at 0.85. Change the level with `--music-vol 0..1`.

## Where to get tracks you can actually use

- **Your own licensed library.** Epidemic Sound, Artlist, Musicbed. If you already pay
  for one, use it. Check whether your plan covers client deliverables, not just your
  own channels.
- **CC0 / public domain.** Free Music Archive and Pixabay Music both carry CC0 tracks.
  Read the specific track's license, not the site's homepage. CC0 on one track does not
  make the whole site CC0.
- **Skip it.** Post the silent cut and let the platform's own audio picker add a trending
  sound. On Reels and TikTok that often outperforms a licensed bed anyway.

## What not to do

Do not pull audio off YouTube or rip a trending sound into an MP4 you hand a client.
That is the one that generates a takedown on their listing, not yours.
