# GTA 6 Clipper (Windows)

Two Claude Code skills and a standalone local-Ollama CLI for turning GTA 6 streams into ready-to-post clips.

- **gta6-clipper** clips a stream that has finished. Give it a YouTube, Twitch or Kick link, or nothing and it finds today's biggest GTA 6 streams.
- **gta6-live-clipper** clips a stream while it's still live. A clip is ready about 5 to 8 minutes after the moment happens.

Every clip comes out 1080x1920: facecam on top, gameplay below, a hook title, word-by-word captions, and a post caption with hashtags.

**Windows version** (Windows 10 or 11, 64-bit). On a Mac? Use the Mac version: https://github.com/vossashtonai/gta6-clipper

## Install

### Option A: install from a reviewed checkout

1. Click Start, type **PowerShell**, open it.
2. Clone the repository, inspect the files, then run the installer from that checkout:

```powershell
git clone https://github.com/vossashtonai/gta6-clipper-windows.git "$env:TEMP\gta6-clipper-windows"
Set-Location "$env:TEMP\gta6-clipper-windows"
Get-Content .\install.ps1
Get-Content .\skills\gta6-clipper\scripts\setup.ps1
powershell -NoProfile -ExecutionPolicy Bypass -File .\install.ps1
```

3. Wait for **READY** (first time takes 5 to 10 minutes).
4. Close and reopen Claude Code, then say **clip this stream** `<link>`.

The installer copies the reviewed checkout. Setup uses Windows Package Manager and a hash-locked Python
requirements file. Review `setup.ps1` and `requirements.lock` before running it.

### Option B: paste this into Claude Code

```text
Clone https://github.com/vossashtonai/gta6-clipper-windows to a temporary folder.
Review the installer and setup scripts before running them. Run install.ps1 from the checkout.
Tell me what setup installed and whether it says READY. Then remind me to restart Claude Code.
```

### Option C: as a Claude Code plugin

In Claude Code:

```text
/plugin marketplace add vossashtonai/gta6-clipper-windows
/plugin install gta6-clipper-windows@ashtonvossai-windows
```

Then say **set up the GTA 6 clipper**.

Review the plugin source before setup; plugin installation fetches skill files directly from GitHub.

### Option D: by hand (PowerShell)

```powershell
git clone https://github.com/vossashtonai/gta6-clipper-windows.git $env:TEMP\gta6-clipper-windows
Set-Location $env:TEMP\gta6-clipper-windows
powershell -NoProfile -ExecutionPolicy Bypass -File .\install.ps1
```

Setup checks what your PC needs and installs what's missing through winget and a hash-locked Python
requirements file: FFmpeg, Deno, uv, the Python environment, and pinned Whisper/YuNet models.
Re-run it if setup reports missing dependencies.

Claude Code is required for the interactive skills. The standalone CLI below does not require Claude Code.
Git for Windows is needed to clone the repository.

## Use it

Open Claude Code and say:

- **clip this stream** `<link>`
- **find me today's biggest GTA 6 streams and clip them**
- **live clip** `<link>` (for a stream that's live right now)

Clips land in `GTA6-Clips` in your user folder (`C:\Users\<you>\GTA6-Clips`). Each one has an `.mp4` and a `.txt` with the title, caption and hashtags.

## How it works

| Step | Finished stream | Live stream | Tools |
|---|---|---|---|
| 1. Get the stream | Downloads the audio only (4 h ≈ 220 MB) | Records 1-minute pieces, keeps the last 15 min | yt-dlp, FFmpeg |
| 2. Speech to text | Whole stream in one go | Each minute as it lands | FFmpeg, faster-whisper |
| 3. Find the hype | Loud seconds + YouTube replay chat speed | Loud seconds + live Twitch chat speed | FFmpeg, chat |
| 4. Pick the moments | Claude Code or the standalone Ollama CLI selects moments | Claude reads each 5-min window, any 7.5+ | Claude Code or Ollama |
| 5. Make the clip | Downloads only those minutes | Cuts from the pieces already on your PC | OpenCV, faster-whisper, Pillow, FFmpeg |

Chat is counted, never read: 10-second buckets, a spike is 8+ messages at 2.5x the normal rate. Loud means 9 dB above the streamer's own normal. The facecam is found by looking for a face, and box edges, that stay still while the gameplay moves.

## Run it free

Picking (step 4) is the only part that uses AI. Everything else runs on your PC. To run without a Claude subscription:

1. Install [Ollama](https://ollama.com).
2. Check your memory (Settings → System → About → Installed RAM). 16 GB: `ollama pull qwen3.5:9b`. 32 GB or more: `ollama pull qwen3.5:27b`.
3. In PowerShell: `ollama launch claude` and pick the model.
4. Same prompts as above.

The free model is slower and its picks are rougher than Claude's. Expect some back and forth.

## Run a URL without Claude Code

Complete setup once, install [Ollama](https://ollama.com/download), and pull a model (16 GB RAM: `qwen3.5:9b`;
32 GB or more: `qwen3.5:27b`). Keep the Ollama app running, or start its server with `ollama serve`.
From the repository folder, run:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\skills\gta6-clipper\scripts\setup.ps1
ollama pull qwen3.5:9b
.\skills\gta6-clipper\.venv\Scripts\python.exe .\skills\gta6-clipper\scripts\gta6clip.py clip-url "https://youtube.com/watch?v=..."
```

`clip-url` detects whether the URL is a finished stream or currently live. For a finished stream it downloads
and transcribes the stream, asks the local model to select moments, and renders up to three clips. For a live
stream it keeps recording and scoring new windows until the stream ends; press Ctrl+C to stop recording and
finish the last window. No Claude Code account or cloud API key is used. Change the model with
`--model qwen3.5:27b`; use `--cookies firefox` for streams that require browser login.

## Good to know

- Installed the Mac version by mistake (it says "Mac only")? Just run the one command above: it replaces it.
- Use Claude Code for Windows itself (the desktop app or `claude` in PowerShell / Git Bash), not Claude Code inside WSL.

- Age-restricted YouTube streams and Kick need your browser login. Tell Claude to use `--cookies firefox`. Chrome and Edge lock their cookies on Windows, so use Firefox or an exported cookies.txt.
- YouTube streams that are still live can be clipped by the finished-stream skill once the replay is up. Twitch past broadcasts work while the stream is still going.
- Twitch in "find me streams" is optional: create a free app at [dev.twitch.tv/console](https://dev.twitch.tv/console) and put `TWITCH_CLIENT_ID` and `TWITCH_CLIENT_SECRET` in `skills\\gta6-clipper\\.env` (see `.env.example`).
- Live clipping needs the Claude Code session to stay open, and run at most 2 streams at once on a 16 GB PC.
- Clip streamers who are fine with clipping, and watch every clip before you post it.
- YouTube ad money needs the Partner Program, and YouTube can refuse it for reposted, mass-made content. Add something of your own.

## Made by

[Ashton Voss AI](https://www.youtube.com/@ashtonvossai). More free AI systems in the AI Alliance Community.

MIT licensed.
