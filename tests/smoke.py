"""End-to-end smoke test, no internet streams needed.

Builds a 150 s fake stream (test pattern + real speech + one loud burst), serves it from a local web
server (throttled to ~2x real time so the live recorder sees it arrive like a stream), then runs:
  VOD:  prep -> (scripted pick) -> render
  LIVE: recorder start -> first window -> status (alive) -> stop -> clip -> recorder gone
Run with the skill venv:  .venv\\Scripts\\python.exe tests\\smoke.py   (after setup.ps1)
"""
import http.server, json, os, shutil, subprocess, sys, tempfile, threading, time, urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SK = Path(os.environ.get("GTA6_SKILLS_DIR", ROOT / "skills"))  # point at %USERPROFILE%\\.claude\\skills to test an install
VOD_DIR, LIVE_DIR = SK / "gta6-clipper", SK / "gta6-live-clipper"
TMP = Path(tempfile.mkdtemp(prefix="gta6-smoke-"))
os.environ["GTA6_CLIPS_DIR"] = str(TMP / "clips")
os.environ["GTA6_LIVE_DIR"] = str(TMP / "live")
sys.path.insert(0, str(VOD_DIR / "scripts"))
sys.path.insert(0, str(LIVE_DIR / "scripts"))
import gta6clip as g  # noqa: E402
import live  # noqa: E402

PY = sys.executable
results = []


def check(name, cond, detail=""):
    results.append((name, bool(cond)))
    print(("PASS " if cond else "FAIL ") + name + (f"  ({detail})" if detail else ""), flush=True)
    return cond


def sh(cmd, **kw):
    r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", **kw)
    if r.returncode != 0:
        print(r.stdout[-1500:], r.stderr[-1500:])
    return r


# ---------------------------------------------------------------- fake stream
speech = TMP / "jfk.flac"
urllib.request.urlretrieve("https://github.com/openai/whisper/raw/main/tests/jfk.flac", speech)
src = TMP / "stream.mp4"
sh(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", "testsrc2=size=1280x720:rate=30",
    "-stream_loop", "-1", "-i", str(speech), "-t", "150",
    "-filter_complex", "[1:a]volume='if(between(t,70,78),6,0.6)':eval=frame,aresample=44100[a]",
    "-map", "0:v", "-map", "[a]", "-c:v", "libx264", "-preset", "ultrafast", "-g", "60",
    "-c:a", "aac", "-movflags", "+faststart", str(src)])
check("fake stream built", src.exists() and src.stat().st_size > 100000)


class Throttled(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *a, **kw):
        super().__init__(*a, directory=str(TMP), **kw)

    def log_message(self, *a):
        pass

    def handle(self):
        try:
            super().handle()
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
            pass  # yt-dlp probes then hangs up: normal

    def copyfile(self, source, outputfile):
        rate = int(os.environ.get("SMOKE_RATE", "0"))  # bytes/s, 0 = full speed
        while True:
            buf = source.read(64 * 1024)
            if not buf:
                break
            outputfile.write(buf)
            if rate:
                time.sleep(len(buf) / rate)


srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Throttled)
threading.Thread(target=srv.serve_forever, daemon=True).start()
URL = f"http://127.0.0.1:{srv.server_address[1]}/stream.mp4"

# ---------------------------------------------------------------- VOD clipper
t = time.time()
r = sh([PY, str(VOD_DIR / "scripts" / "gta6clip.py"), "prep", URL])
runs = [p for p in (TMP / "clips").iterdir() if p.is_dir()] if (TMP / "clips").exists() else []
runs = [p for p in runs if (p / "chunks" / "chunk_01.md").exists()]
check("prep finished", r.returncode == 0 and runs, f"{time.time() - t:.0f}s")
if runs:
    rd = runs[0]
    chunk = (rd / "chunks" / "chunk_01.md").read_text(encoding="utf-8")
    check("VOD transcript marked untrusted", chunk.splitlines()[0] == g.UNTRUSTED_TRANSCRIPT_NOTICE)
    check("transcript has speech", "country" in chunk.lower(), chunk.splitlines()[5][:80] if len(chunk.splitlines()) > 5 else "")
    check("loud burst marked", "LOUD(" in chunk)
    (rd / "picks" / "chunk_01.json").write_text(json.dumps([{
        "start": "00:01:05", "end": "00:01:30", "score": 8.5, "category": "hype", "title": "Smoke test clip",
        "hook": "HE DID NOT SEE THAT COMING", "caption": "smoke test", "hashtags": ["#GTA6"]}]), encoding="utf-8")
    t = time.time()
    r = sh([PY, str(VOD_DIR / "scripts" / "gta6clip.py"), "render", str(rd)])
    mp4s = list((rd / "clips").glob("*.mp4"))
    check("render made a clip", r.returncode == 0 and mp4s, f"{time.time() - t:.0f}s")
    if mp4s:
        pr = json.loads(sh(["ffprobe", "-v", "error", "-show_entries", "stream=codec_type,width,height",
                            "-of", "json", str(mp4s[0])]).stdout)
        v = [s for s in pr["streams"] if s["codec_type"] == "video"][0]
        check("clip is 1080x1920 with audio", (v["width"], v["height"]) == (1080, 1920)
              and any(s["codec_type"] == "audio" for s in pr["streams"]))
        check("clip caption txt", mp4s[0].with_suffix(".txt").exists())

# ---------------------------------------------------------------- LIVE clipper
os.environ["SMOKE_RATE"] = str(int(src.stat().st_size / 70))  # whole file in ~70 s (about 2x real time)
lrd = TMP / "live" / "smoke-run"
lrd.mkdir(parents=True)
live.jsave(lrd / "stream.json", {"url": URL, "webpage_url": URL, "streamer": "smoke", "title": "smoke live",
                                 "cookies": None, "quality": 720, "buffer_min": 15, "window_min": 1})
live.jsave(lrd / "state.json", {"windows": 0})
p = live.spawn_daemon([PY, str(LIVE_DIR / "scripts" / "live.py"), "_daemon", str(lrd)], lrd / "daemon.log")
(lrd / "pid").write_text(str(p.pid), encoding="utf-8")
LCMD = [PY, str(LIVE_DIR / "scripts" / "live.py")]

r = sh(LCMD + ["next", str(lrd), "--wait", "150"])
check("live: first window arrived", "WINDOW: window_001.md" in r.stdout, r.stdout.splitlines()[0] if r.stdout else r.stderr[-200:])
window = (lrd / "windows" / "window_001.md").read_text(encoding="utf-8")
check("live transcript marked untrusted", window.splitlines()[0] == g.UNTRUSTED_TRANSCRIPT_NOTICE)
st = json.loads(sh(LCMD + ["status", str(lrd)]).stdout)
check("live: status sees recorder alive", st.get("recorder_running") is True, json.dumps(st))
(lrd / "picks" / "window_001.json").write_text(json.dumps([{
    "start": "00:00:20", "end": "00:00:45", "score": 8.0, "category": "funny", "title": "Live smoke clip",
    "hook": "LIVE TEST", "caption": "live smoke", "hashtags": ["#GTA6"]}]), encoding="utf-8")
r = sh(LCMD + ["clip", str(lrd)])
check("live: clip rendered from buffer", list((lrd / "clips").glob("*.mp4")), r.stdout.strip().splitlines()[-1] if r.stdout.strip() else r.stderr[-300:])
r = sh(LCMD + ["stop", str(lrd)])
check("live: stop accepted", "stopping" in r.stdout, r.stdout.strip())
dead = False
for _ in range(60):
    if p.poll() is not None:  # reaps it on Mac/Linux too (else it lingers as a zombie of this test)
        dead = True
        break
    time.sleep(1)
check("live: recorder exited after stop", dead)
state = live.jload(lrd / "state.json", {})
check("live: last window written, run marked ended", state.get("ended") is True and state.get("windows", 0) >= 1, json.dumps(state))
check("live: no pid reuse false positive", json.loads(sh(LCMD + ["status", str(lrd)]).stdout).get("recorder_running") is False)
for f in ("daemon.log", "ffmpeg.log", "ytdlp.log"):
    if (lrd / f).exists() and (lrd / f).stat().st_size:
        print(f"--- {f}\n" + (lrd / f).read_text(encoding="utf-8", errors="replace")[-1500:])

srv.shutdown()
failed = [n for n, ok in results if not ok]
print(f"\n{len(results) - len(failed)}/{len(results)} passed" + (f". FAILED: {failed}" if failed else ""))
if not failed and not os.environ.get("SMOKE_KEEP"):
    shutil.rmtree(TMP, ignore_errors=True)
sys.exit(1 if failed else 0)
