# GTA 6 Clipper (Claude Code skill and standalone CLI)

An AI that clips GTA 6 streams for you. Give it a stream link from YouTube, Twitch or Kick (or nothing,
and it finds today's biggest GTA 6 streams) and you get ready-to-post vertical clips: facecam on top,
gameplay below, a hook title, word-by-word captions, and a post caption with hashtags.

## What it does, in 4 steps

1. **Downloads only the audio.** A 4-hour stream is a couple hundred MB, not a giant video file.
2. **Listens to the whole stream on your PC:** a transcript, where the streamer got loud, and (on YouTube
   replays) where chat suddenly sped up.
3. **The AI reads the transcript 12 minutes at a time** and picks what people share: first reactions,
   crazy discoveries, freakouts, funny fails, hot takes. Every moment gets a score, and anything that
   needs context gets thrown out.
4. **Downloads only the minutes it needs,** finds the facecam by itself and makes the clips, plus a
   caption and hashtags for each one.

3 clips per stream by default. Several streams run at once.

## Way 1: your Claude subscription (best)

Plans start at $20/month. No API keys. Everything except the picking runs on your PC.

1. Put this `gta6-clipper` folder in `~/.claude/skills/`.
2. Open Claude Code and say: **set up the GTA 6 clipper**. It checks what your PC needs, installs what's
   missing and tells you when it's ready.
3. Say: **clip this stream** and paste the link. Or: **find me today's biggest GTA 6 streams and clip them**.

## Way 2: free (no subscription, no API key)

1. Install [Ollama](https://ollama.com) and Claude Code (both free).
2. Check your memory, not your storage: Start menu -> Settings > System > About -> Memory.
3. 16 GB -> `ollama pull qwen3.5:9b`. 32 GB or more -> `ollama pull qwen3.5:27b`.
4. In Terminal: `ollama launch claude` and pick your model.
5. Same prompts as Way 1.

Honest take: the free model isn't Claude. It's slower, the picks are rougher, and expect some back and
forth. It still beats scrubbing a stream by hand.

## Way 3: standalone URL-to-clips CLI (no Claude Code)

Set up the skill dependencies once, install Ollama, and pull a local model. 16 GB RAM: `qwen3.5:9b`;
32 GB or more: `qwen3.5:27b`. Keep Ollama running. From the repository root, run:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\skills\gta6-clipper\scripts\setup.ps1
ollama pull qwen3.5:9b
.\skills\gta6-clipper\.venv\Scripts\python.exe .\skills\gta6-clipper\scripts\gta6clip.py clip-url "https://youtube.com/watch?v=..."
```

The CLI detects finished and live URLs. For a finished stream, it prepares the stream, asks Ollama to pick
moments, and renders up to three clips automatically. For a live stream, it keeps recording and scoring
windows until the stream ends; press Ctrl+C to stop and finish the last window. Use `--model qwen3.5:27b`
to select another model or `--cookies firefox` for login-protected streams. The default model is `qwen3.5:9b`.

## Good to know

- Windows 10 or 11 (64-bit). Mac version: https://github.com/vossashtonai/gta6-clipper
- Age-restricted YouTube streams (common with GTA) and Kick need your browser login: tell Claude to use
  `--cookies chrome`.
- YouTube streams that are still live can be clipped once the replay is up. Twitch archives work while live.
- Twitch in "find me streams" is optional: create a free app at dev.twitch.tv/console and put
  `TWITCH_CLIENT_ID=` and `TWITCH_CLIENT_SECRET=` in `gta6-clipper/.env`. Without it, discovery uses YouTube
  and you can still paste any Twitch link.
- Clip streamers who are fine with clipping, and watch every clip before you post it.
- YouTube ad money needs the Partner Program, and YouTube can refuse it for reposted, mass-made content.
  Add something of your own.

## Files

```
SKILL.md                 instructions Claude follows
references/picking.md    how the AI picks and scores moments
scripts/setup.ps1        installs everything (ffmpeg, faster-whisper, yt-dlp, OpenCV...)
scripts/gta6clip.py      discover / prep / clip-url / status / render
~/GTA6-Clips/<run>/     transcript, chunks, picks, clips/ (live runs in ~/GTA6-Clips/live/)
```
