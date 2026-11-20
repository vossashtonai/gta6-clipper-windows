# Community post: GTA 6 Clipper for Windows (copy-paste)

**Title:** GTA 6 Clipper for WINDOWS: free Claude Code skills (finished + live)

Here are both GTA 6 clipper skills from the video. This is the Windows version (Windows 10/11). Mac version: https://github.com/vossashtonai/gta6-clipper

**1. Open PowerShell** (click Start, type PowerShell, open it), then clone and inspect the repository:

```powershell
git clone https://github.com/vossashtonai/gta6-clipper-windows.git "$env:TEMP\gta6-clipper-windows"
Set-Location "$env:TEMP\gta6-clipper-windows"
Get-Content .\install.ps1
Get-Content .\skills\gta6-clipper\scripts\setup.ps1
powershell -NoProfile -ExecutionPolicy Bypass -File .\install.ps1
```

Wait until it says READY (first time 5 to 10 minutes).

**2. Restart Claude Code, then say one of these:**

- clip this stream [paste link]
- find me today's biggest GTA 6 streams and clip them
- live clip [paste link of a stream that's live right now]

Your clips land in a folder called GTA6-Clips in your user folder (C:\Users\you\GTA6-Clips), each with a caption and hashtags ready to post.

**No Claude subscription?** The README on GitHub shows how to run it free with Ollama.

Drop your first clip in the comments
