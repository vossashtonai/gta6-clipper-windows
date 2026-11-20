#!/usr/bin/env python3
"""GTA 6 LIVE Clipper: clips a stream WHILE it's live.

  start URL [URL...]   start recording each live stream into a rolling local buffer (background)
  next RUN [RUN...]    wait for the next 5-minute transcript window (from any of the runs) and print it
  clip RUN [RUN...]    render every new pick straight from the local buffer (no re-download)
  status RUN [RUN...]  what each recorder is doing
  stop RUN [RUN...]    stop recording (buffer is cleaned up; clips stay)

The recorder (hidden `_daemon` command) keeps 1-minute video segments for --buffer-min minutes,
transcribes each one on this PC as it lands, tracks loudness and (Twitch) chat speed, and writes
windows/window_NNN.md every --window-min minutes. Claude reads each window and writes
picks/window_NNN.json (same format as the VOD clipper). Shares the gta6-clipper engine + venv.
"""
import argparse, csv, json, os, random, signal, socket, statistics, subprocess, sys, threading, time
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
VOD = Path(os.environ.get("GTA6_CLIPPER_DIR", HERE.parent / "gta6-clipper"))
sys.path.insert(0, str(VOD / "scripts"))
import gta6clip as g  # noqa: E402

RUNS = Path(os.environ.get("GTA6_LIVE_DIR", Path.home() / "GTA6-Clips" / "live"))
SEG = 60


def log(*a):
    print(*a, flush=True)


def jload(p, default):
    try:
        return json.loads(Path(p).read_text(encoding="utf-8"))
    except Exception:
        return default


def jsave(p, obj):
    tmp = Path(str(p) + ".tmp")
    tmp.write_text(json.dumps(obj, indent=1), encoding="utf-8")
    for i in range(20):  # Windows refuses the swap while another process is reading the file: retry
        try:
            tmp.replace(p)
            return
        except PermissionError:
            time.sleep(0.05 * (i + 1))
    Path(p).write_text(tmp.read_text(encoding="utf-8"), encoding="utf-8")


def pid_alive(pid):
    """os.kill(pid, 0) is NOT safe on Windows (signal 0 = Ctrl+C). Ask the kernel instead."""
    if os.name != "nt":
        try:
            os.kill(pid, 0)
            return True
        except OSError:
            return False
    import ctypes
    k = ctypes.windll.kernel32
    h = k.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
    if not h:
        return False
    code = ctypes.c_ulong()
    ok = k.GetExitCodeProcess(h, ctypes.byref(code))
    k.CloseHandle(h)
    return bool(ok) and code.value == 259  # STILL_ACTIVE


def kill_tree(proc):
    if proc.poll() is not None:
        return
    if os.name == "nt":
        subprocess.run(["taskkill", "/PID", str(proc.pid), "/T", "/F"], capture_output=True,
                       creationflags=g.NO_WINDOW)
    else:
        proc.terminate()


# ================================================================ daemon (runs in background)
class Daemon:
    def __init__(self, rd):
        self.rd = rd
        self.cfg = jload(rd / "stream.json", {})
        self.state = jload(rd / "state.json", {})
        self.seg_dir = rd / "buffer"
        self.seg_dir.mkdir(exist_ok=True)
        (rd / "windows").mkdir(exist_ok=True)
        (rd / "picks").mkdir(exist_ok=True)
        self.transcript = jload(rd / "transcript.json", [])
        self.rms = []          # (stream_t, dB) per second
        self.loud = []         # {"start","end","db"}
        self.chat_times = []   # stream time of each chat message
        self.done_segs = set(jload(rd / "segments.json", {}).keys())
        self.t0_wall = None
        self.stop = False

    def save_state(self, **kw):
        self.state.update(kw, updated=time.time())
        jsave(self.rd / "state.json", self.state)

    # ---- recorder: yt-dlp -> ffmpeg 1-minute segments
    def record(self):
        q = self.cfg.get("quality", 720)
        cmd = g.YTDLP + g.cookie_args(self.cfg.get("cookies")) + [
            "-f", f"best[height<={q}]/bv*[height<={q}]+ba/best", "-o", "-", self.cfg["url"]]
        ff = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-i", "pipe:0", "-map", "0:v:0", "-map", "0:a:0",
              "-c", "copy", "-f", "segment", "-segment_time", str(SEG), "-reset_timestamps", "1",
              "-segment_list", str(self.rd / "segs.csv"), "-segment_list_type", "csv",
              str(self.seg_dir / "seg_%05d.ts")]
        self.t0_wall = time.time()
        self.save_state(recording=True, started_wall=self.t0_wall)
        yt = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=open(self.rd / "ytdlp.log", "ab"),
                              creationflags=g.NO_WINDOW)
        ffp = subprocess.Popen(ff, stdin=yt.stdout, stderr=open(self.rd / "ffmpeg.log", "ab"),
                               creationflags=g.NO_WINDOW)
        yt.stdout.close()
        self.procs = [yt, ffp]
        ffp.wait()
        yt.wait()
        self.save_state(recording=False, ended_wall=time.time())

    # ---- Twitch chat speed (official anonymous read-only chat connection)
    def chat(self):
        url = self.cfg["url"]
        if "twitch.tv" not in url:
            return
        chan = url.rstrip("/").split("/")[-1].lower()
        while not self.stop:
            try:
                s = socket.create_connection(("irc.chat.twitch.tv", 6667), timeout=30)
                s.sendall(f"NICK justinfan{random.randint(10000, 99999)}\r\nJOIN #{chan}\r\n".encode())
                buf = b""
                while not self.stop:
                    data = s.recv(4096)
                    if not data:
                        break
                    buf += data
                    *lines, buf = buf.split(b"\r\n")
                    for ln in lines:
                        if ln.startswith(b"PING"):
                            s.sendall(b"PONG :tmi.twitch.tv\r\n")
                        elif b" PRIVMSG " in ln and self.t0_wall:
                            self.chat_times.append(time.time() - self.t0_wall)
            except Exception:
                time.sleep(10)

    def chat_spikes(self, a, b):
        """10-second bins between a and b vs the trailing 5-minute median."""
        out = []
        t = a - a % 10
        while t < b:
            c = sum(1 for x in self.chat_times if t <= x < t + 10)
            hist = [sum(1 for x in self.chat_times if u <= x < u + 10) for u in range(int(t - 300), int(t), 10)]
            base = max(1.0, statistics.median(hist)) if hist else 1.0
            if c >= 8 and c / base >= 2.5:
                out.append({"start": t, "end": t + 10, "x": round(c / base, 1)})
            t += 10
        return out

    # ---- processor: transcribe + loudness for each finished segment
    def segments(self):
        rows = []
        p = self.rd / "segs.csv"
        if p.exists():
            for r in csv.reader(p.read_text(encoding="utf-8").splitlines()):
                if len(r) >= 3:
                    rows.append((r[0], float(r[1]), float(r[2])))
        # ffmpeg writes cumulative times; normalise to stream time from the first segment
        if rows:
            base = rows[0][1]
            rows = [(f, s - base, e - base) for f, s, e in rows]
        return rows

    def process_segment(self, fname, st, en):
        f = self.seg_dir / fname
        wav = self.rd / "seg.wav"
        g.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(f), "-vn", "-ac", "1", "-ar", "16000", str(wav)])
        try:
            segs = g.transcribe(wav, self.rd / "seg_whisper")
        except Exception:
            segs = []
        r = g.run(["ffmpeg", "-hide_banner", "-nostats", "-i", str(wav), "-af",
                   "asetnsamples=n=16000,astats=metadata=1:reset=1,ametadata=print:key=lavfi.astats.Overall.RMS_level:file=-",
                   "-f", "null", "-"])
        import re
        vals = [(-90.0 if v == "-inf" else float(v)) for v in re.findall(r"RMS_level=(-?[\d.]+|-inf)", r.stdout)]
        for i, v in enumerate(vals):
            t = st + i
            hist = [x for _, x in self.rms[-180:]] or [v]
            base = statistics.median(hist)
            self.rms.append((t, v))
            if v > -32 and v - base >= 9:
                if self.loud and t - self.loud[-1]["end"] <= 2:
                    self.loud[-1]["end"] = t
                    self.loud[-1]["db"] = max(self.loud[-1]["db"], round(v - base, 1))
                else:
                    self.loud.append({"start": t, "end": t, "db": round(v - base, 1)})
        for s in segs:
            self.transcript.append({"start": s["start"] + st, "end": min(s["end"], en - st) + st, "text": s["text"]})
        wav.unlink(missing_ok=True)
        jsave(self.rd / "transcript.json", self.transcript)
        jsave(self.rd / "signals.json", {"loud": self.loud})

    def write_windows(self, covered):
        W = self.cfg.get("window_min", 5) * 60
        k = self.state.get("windows", 0)
        while (k + 1) * W <= covered:
            a, b = max(0, k * W - 45), (k + 1) * W  # 45 s overlap so nothing is cut in half
            chat = self.chat_spikes(a, b)
            lines = [g.UNTRUSTED_TRANSCRIPT_NOTICE,
                     f"# LIVE {self.cfg.get('streamer')}: {self.cfg.get('title')}",
                     f"Window {k + 1}  ({g.hms(a)} to {g.hms(b)} of the recording)",
                     "Markers: LOUD(+dB over normal) = streamer got loud. CHAT xN = chat moving N times faster than normal.", ""]
            for s in self.transcript:
                if s["end"] <= a or s["start"] >= b:
                    continue
                tags = [f"LOUD(+{e['db']:.0f}dB)" for e in self.loud if e["start"] <= s["end"] and e["end"] + 1 >= s["start"]][:1]
                tags += [f"CHAT x{e['x']}" for e in chat if e["start"] - 15 <= s["end"] and e["end"] >= s["start"]][:1]
                lines.append(f"[{g.hms(s['start'])}] {s['text']}" + (f"   <<{' '.join(tags)}>>" if tags else ""))
            (self.rd / "windows" / f"window_{k + 1:03d}.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
            k += 1
            self.save_state(windows=k)

    def flush_last_window(self, covered):
        W = self.cfg.get("window_min", 5) * 60
        k = self.state.get("windows", 0)
        if covered - k * W > 60:  # stream ended mid-window: write the partial one
            self.cfg["window_min_override"] = True
            a, b = max(0, k * W - 45), covered
            lines = [g.UNTRUSTED_TRANSCRIPT_NOTICE,
                     f"# LIVE {self.cfg.get('streamer')}: {self.cfg.get('title')}",
                     f"Window {k + 1} (final, {g.hms(a)} to {g.hms(b)})",
                     ""]
            lines += [f"[{g.hms(s['start'])}] {s['text']}" for s in self.transcript if a < s["end"] and s["start"] < b]
            (self.rd / "windows" / f"window_{k + 1:03d}.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
            self.save_state(windows=k + 1)

    def cleanup_buffer(self, newest_end):
        keep_from = newest_end - self.cfg.get("buffer_min", 15) * 60
        held = jload(self.rd / "hold.json", [])  # [start,end] ranges the clip step still needs
        for f, s, e in self.segments():
            if e < keep_from and not any(e >= h[0] and s <= h[1] for h in held):
                try:
                    (self.seg_dir / f).unlink(missing_ok=True)
                except OSError:
                    pass  # a clip render has it open right now (Windows file lock): delete it next pass

    def run(self):
        threading.Thread(target=self.record, daemon=True).start()
        threading.Thread(target=self.chat, daemon=True).start()
        signal.signal(signal.SIGTERM, lambda *_: self.shutdown())
        time.sleep(5)
        while True:
            if (self.rd / "stop").exists() and not getattr(self, "stopping", False):
                self.stopping = self.shutdown()  # False until the recorder has actually started
            rows = self.segments()
            meta = jload(self.rd / "segments.json", {})
            for f, s, e in rows:
                if f not in self.done_segs:
                    self.process_segment(f, s, e)
                    self.done_segs.add(f)
                    meta[f] = [s, e]
                    jsave(self.rd / "segments.json", meta)
            covered = rows[-1][2] if rows else 0
            self.save_state(covered=covered, segments=len(rows))
            self.write_windows(covered)
            if rows:
                self.cleanup_buffer(covered)
            if not self.state.get("recording") and self.state.get("ended_wall"):
                # pick up the last segment ffmpeg closed on exit, then finish
                if all(f in self.done_segs for f, _, _ in self.segments()):
                    self.flush_last_window(covered)
                    self.save_state(ended=True)
                    self.stop = True
                    return
            time.sleep(5)

    def shutdown(self):
        """Stop yt-dlp; ffmpeg then sees the end of its input and closes the last segment cleanly."""
        procs = getattr(self, "procs", [])
        if not procs:
            return False
        try:
            kill_tree(procs[0])
            procs[1].wait(timeout=15)
        except Exception:
            for p in procs:
                try:
                    kill_tree(p)
                except Exception:
                    pass
        return True


# ================================================================ CLI
def cmd_start(a):
    RUNS.mkdir(parents=True, exist_ok=True)
    runs = []
    for url in a.urls:
        try:
            meta = g.ytdlp_json(url, a.cookies, ["--no-playlist"])
        except Exception as e:
            log(f"FAILED {url}: {e}")
            continue
        if not meta.get("is_live") and meta.get("live_status") != "is_live":
            log(f"NOT LIVE: {url}  (for finished streams use the gta6-clipper skill)")
            continue
        streamer = meta.get("uploader") or meta.get("channel") or "streamer"
        rd = RUNS / f"{time.strftime('%Y-%m-%d-%H%M')}-{g.slug(streamer, 24)}"
        rd.mkdir(parents=True, exist_ok=True)
        jsave(rd / "stream.json", {"url": url, "webpage_url": meta.get("webpage_url") or url, "streamer": streamer,
                                   "title": meta.get("title"), "cookies": a.cookies, "quality": a.quality,
                                   "buffer_min": a.buffer_min, "window_min": a.window_min})
        jsave(rd / "state.json", {"windows": 0})
        p = spawn_daemon([sys.executable, __file__, "_daemon", str(rd)], rd / "daemon.log")
        (rd / "pid").write_text(str(p.pid), encoding="utf-8")
        log(f"RECORDING {streamer}: {meta.get('title')}\n  run: {rd}")
        runs.append(rd)
    return runs


def spawn_daemon(cmd, logf):
    """Background recorder that outlives this command and never opens a console window."""
    out = open(logf, "ab")
    if os.name != "nt":
        return subprocess.Popen(cmd, start_new_session=True, stdout=out, stderr=subprocess.STDOUT)
    base = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NO_WINDOW
    try:  # break out of the terminal's job so closing it doesn't kill the recorder
        return subprocess.Popen(cmd, creationflags=base | 0x01000000, stdout=out, stderr=subprocess.STDOUT,
                                stdin=subprocess.DEVNULL)
    except OSError:
        return subprocess.Popen(cmd, creationflags=base, stdout=out, stderr=subprocess.STDOUT,
                                stdin=subprocess.DEVNULL)


def pending_windows(rd):
    done = {p.stem for p in (rd / "picks").glob("window_*.json")}
    return [w for w in sorted((rd / "windows").glob("window_*.md")) if w.stem not in done]


def cmd_next(a):
    runs = [Path(r) for r in a.runs]
    deadline = time.time() + a.wait
    while True:
        for rd in runs:
            pw = pending_windows(rd)
            if pw:
                w = pw[0]
                log(f"RUN: {rd}\nWINDOW: {w.name}  ->  write {rd / 'picks' / (w.stem + '.json')}\n")
                log(w.read_text(encoding="utf-8"))
                return
        if all(jload(rd / "state.json", {}).get("ended") for rd in runs):
            log("STREAM ENDED: no more windows. Run clip one last time, then report.")
            return
        if time.time() > deadline:
            st = {rd.name: jload(rd / "state.json", {}).get("covered", 0) for rd in runs}
            log(f"NO NEW WINDOW YET (recorded so far: { {k: g.hms(v) for k, v in st.items()} }). Run next again.")
            return
        time.sleep(5)


def cmd_clip(a):
    for r in a.runs:
        rd = Path(r)
        info = jload(rd / "stream.json", {})
        rendered = jload(rd / "rendered.json", [])
        meta = jload(rd / "segments.json", {})
        segs = sorted((s, e, f) for f, (s, e) in meta.items() if (rd / "buffer" / f).exists())
        cands = []
        for p in sorted((rd / "picks").glob("window_*.json")):
            for c in jload(p, []):
                try:
                    c["_s"], c["_e"] = g.parse_ts(c["start"]), g.parse_ts(c["end"])
                    if float(c.get("score", 0)) >= a.min_score and 12 <= c["_e"] - c["_s"] <= 75:
                        cands.append(c)
                except Exception:
                    pass
        new = 0
        for c in sorted(cands, key=lambda c: -float(c["score"])):
            if any(not (c["_e"] + 10 < x["_s"] or c["_s"] > x["_e"] + 10) for x in rendered):
                continue
            need = [x for x in segs if x[1] > c["_s"] - 3 and x[0] < c["_e"] + 1]
            if not need or need[0][0] > c["_s"] - 3 or need[-1][1] < c["_e"]:
                log(f"  skipped (out of buffer): {c.get('title')}")
                rendered.append({**c, "skipped": "out of buffer"})
                continue
            n = len([x for x in rendered if not x.get("skipped")]) + 1
            work = rd / f"work_{n:02d}"
            work.mkdir(exist_ok=True)
            lst = work / "segs.txt"
            lst.write_text("".join(f"file '{(rd / 'buffer' / f).resolve().as_posix()}'\n" for _, _, f in need), encoding="utf-8")
            src = work / "src.ts"
            g.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", str(lst), "-c", "copy", str(src)])
            try:
                out, mode = g.render_one(rd, info, c, n, None, a.keep, local_src=src, src_start=need[0][0])
                rendered.append({k: v for k, v in c.items()} | {"file": str(out), "layout": mode})
                new += 1
                log(f"  CLIP {n}: {c.get('title')}  ({g.hms(c['_s'])}, {round(c['_e'] - c['_s'])}s, {mode}) -> {out}")
            except Exception as e:
                log(f"  clip FAILED: {c.get('title')}: {e}")
                rendered.append({**c, "skipped": str(e)[:200]})
            jsave(rd / "rendered.json", rendered)
        log(f"[{info.get('streamer')}] {new} new clip(s). Total: {len([x for x in rendered if not x.get('skipped')])} in {rd / 'clips'}")


def cmd_status(a):
    for r in a.runs:
        rd = Path(r)
        st, info = jload(rd / "state.json", {}), jload(rd / "stream.json", {})
        rendered = [x for x in jload(rd / "rendered.json", []) if not x.get("skipped")]
        try:
            alive = pid_alive(int((rd / "pid").read_text(encoding="utf-8")))
        except Exception:
            alive = False
        log(json.dumps({"run": str(rd), "streamer": info.get("streamer"), "recorder_running": alive,
                        "recorded": g.hms(st.get("covered", 0)), "windows": st.get("windows", 0),
                        "windows_waiting_for_picks": [w.name for w in pending_windows(rd)],
                        "clips": len(rendered), "ended": st.get("ended", False)}, indent=1))


def cmd_stop(a):
    """Drop a stop file: the recorder ends yt-dlp, lets ffmpeg close the last segment, writes the last window."""
    for r in a.runs:
        rd = Path(r)
        try:
            pid = int((rd / "pid").read_text(encoding="utf-8"))
        except Exception:
            pid = None
        if not pid or not pid_alive(pid):
            log(f"{rd.name}: not running")
            continue
        (rd / "stop").write_text(time.ctime(), encoding="utf-8")
        log(f"stopping {rd.name} (last window is written once the recorder closes)")


def process_ollama_window(rd, window, base_url, model, min_score):
    info = jload(rd / "stream.json", {})
    transcript = jload(rd / "transcript.json", [])
    covered = jload(rd / "state.json", {}).get("covered", 0)
    duration = max((float(segment["end"]) for segment in transcript), default=float(covered))
    response = g.ollama_pick_chunk(
        base_url, model, info["streamer"], info.get("title", ""),
        window.read_text(encoding="utf-8"), min_score,
    )
    picks = g.validate_ollama_candidates(response, info["streamer"], duration, min_score)
    output = rd / "picks" / f"{window.stem}.json"
    jsave(output, picks)
    log(f"  {window.name}: {len(picks)} candidate(s)")
    return picks


def process_pending_ollama_windows(rd, base_url, model, min_score, keep):
    for window in pending_windows(rd):
        picks = process_ollama_window(rd, window, base_url, model, min_score)
        if picks:
            cmd_clip(argparse.Namespace(runs=[str(rd)], min_score=min_score, keep=keep))


def cmd_clip_url(a):
    if not 0 <= a.min_score <= 10:
        sys.exit("--min-score must be between 0 and 10")
    try:
        base_url = g.normalize_ollama_url(a.ollama_url)
        g.require_ollama_model(base_url, a.model)
    except (RuntimeError, ValueError) as exc:
        sys.exit(f"Local Ollama setup error: {exc}")

    runs = cmd_start(argparse.Namespace(
        urls=[a.url], cookies=a.cookies, quality=a.quality,
        buffer_min=a.buffer_min, window_min=a.window_min,
    ))
    if not runs:
        sys.exit("Could not start recording. Check the URL and stream status above.")
    rd = runs[0]
    log(f"Automatically clipping live stream. Press Ctrl+C to stop recording and finish its last window.")
    try:
        while True:
            process_pending_ollama_windows(rd, base_url, a.model, a.min_score, a.keep)
            state = jload(rd / "state.json", {})
            if state.get("ended") and not pending_windows(rd):
                cmd_clip(argparse.Namespace(runs=[str(rd)], min_score=a.min_score, keep=a.keep))
                log(f"Live stream finished. Clips are in {rd / 'clips'}")
                return
            if not pid_alive(int((rd / "pid").read_text(encoding="utf-8"))):
                if not state.get("ended"):
                    raise RuntimeError(f"Live recorder stopped unexpectedly. Check {rd / 'daemon.log'}")
            time.sleep(2)
    except KeyboardInterrupt:
        log("Stopping the live recorder and finishing its last window...")
        cmd_stop(argparse.Namespace(runs=[str(rd)]))
        while pid_alive(int((rd / "pid").read_text(encoding="utf-8"))):
            time.sleep(2)
        process_pending_ollama_windows(rd, base_url, a.model, a.min_score, a.keep)
        cmd_clip(argparse.Namespace(runs=[str(rd)], min_score=a.min_score, keep=a.keep))
        log(f"Stopped. Clips are in {rd / 'clips'}")
    except Exception:
        cmd_stop(argparse.Namespace(runs=[str(rd)]))
        raise


def main():
    if not (VOD / ".ready").exists():
        sys.exit(f"Set up the GTA 6 clipper first: powershell -NoProfile -ExecutionPolicy Bypass -File \"{VOD / 'scripts' / 'setup.ps1'}\"")
    p = argparse.ArgumentParser()
    sp = p.add_subparsers(dest="cmd", required=True)
    s = sp.add_parser("start"); s.add_argument("urls", nargs="+"); s.add_argument("--cookies")
    s.add_argument("--quality", type=int, default=720); s.add_argument("--buffer-min", type=int, default=15)
    s.add_argument("--window-min", type=int, default=5)
    n = sp.add_parser("next"); n.add_argument("runs", nargs="+"); n.add_argument("--wait", type=int, default=540)
    c = sp.add_parser("clip"); c.add_argument("runs", nargs="+"); c.add_argument("--min-score", type=float, default=7.5)
    c.add_argument("--keep", action="store_true")
    auto = sp.add_parser("clip-url", help="record a live URL and automatically select and render clips with Ollama")
    auto.add_argument("url")
    auto.add_argument("--model", default=os.environ.get("GTA6_OLLAMA_MODEL", "qwen3.5:9b"))
    auto.add_argument("--ollama-url", default=os.environ.get("OLLAMA_HOST", "http://127.0.0.1:11434"))
    auto.add_argument("--cookies")
    auto.add_argument("--quality", type=int, default=720)
    auto.add_argument("--buffer-min", type=int, default=15)
    auto.add_argument("--window-min", type=int, default=5)
    auto.add_argument("--min-score", type=float, default=7.5)
    auto.add_argument("--keep", action="store_true")
    for name in ("status", "stop"):
        x = sp.add_parser(name); x.add_argument("runs", nargs="+")
    d = sp.add_parser("_daemon"); d.add_argument("run")
    a = p.parse_args()
    if a.cmd == "_daemon":
        Daemon(Path(a.run)).run()
        return
    {"start": cmd_start, "next": cmd_next, "clip": cmd_clip, "clip-url": cmd_clip_url,
     "status": cmd_status, "stop": cmd_stop}[a.cmd](a)


if __name__ == "__main__":
    main()
