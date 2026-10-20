"""End-to-end check of everything except the two paid AI calls.

What is real here: HTTP upload, private storage, job queue, ffprobe validation,
FFmpeg audio extraction, boundary snapping, caption files, FFmpeg rendering,
thumbnails, signed preview/download URLs with range requests.

What is stubbed (test only, never in the app): the speech-to-text response and
the Claude highlight picks, because those need your API keys. Run
tests/live_check.py after adding keys to exercise them for real.

Usage:  python tests/smoke_test.py
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
tmp = Path(tempfile.mkdtemp(prefix="scu-test-"))
os.environ["SCU_DATA_DIR"] = str(tmp / "data")
os.environ["SCU_SECRET"] = "test-secret"
sys.path.insert(0, str(ROOT))

import requests  # noqa: E402

from app import ai, db, media, pipeline, youtube  # noqa: E402

PORT = 8765
BASE = f"http://127.0.0.1:{PORT}"
ok = lambda m: print(f"  PASS  {m}")


def make_video(path: Path, seconds: int = 300) -> None:
    subprocess.run(["ffmpeg", "-y", "-v", "error",
                    "-f", "lavfi", "-i", f"testsrc2=size=1920x1080:rate=30:duration={seconds}",
                    "-f", "lavfi", "-i", f"sine=frequency=220:duration={seconds}",
                    "-c:v", "libx264", "-preset", "ultrafast", "-c:a", "aac", "-shortest", str(path)], check=True)


def fake_transcript(duration: float) -> dict:
    """Words every 0.4 s, sentences of 12 words. Stands in for the STT response shape."""
    words, segs, t, n = [], [], 0.5, 0
    vocab = "so the thing nobody tells you about editing is that pacing matters more than effects".split()
    while t < duration - 1:
        sent = []
        for i in range(12):
            w = {"word": vocab[(n + i) % len(vocab)], "start": round(t, 2), "end": round(t + 0.32, 2)}
            words.append(w); sent.append(w); t += 0.4
        segs.append({"text": " ".join(x["word"] for x in sent), "start": sent[0]["start"], "end": sent[-1]["end"]})
        n += 12; t += 0.5
    return {"language": "en", "words": words, "segments": segs}


def main() -> int:
    print("Unit checks")
    cases = {
        "https://www.youtube.com/watch?v=dQw4w9WgXcQ&t=42": "dQw4w9WgXcQ",
        "https://youtu.be/dQw4w9WgXcQ?si=abc": "dQw4w9WgXcQ",
        "youtube.com/shorts/dQw4w9WgXcQ": "dQw4w9WgXcQ",
        "https://m.youtube.com/watch?v=dQw4w9WgXcQ": "dQw4w9WgXcQ",
        "https://vimeo.com/123": None, "https://youtube.com/watch?v=short": None,
    }
    for url, want in cases.items():
        assert youtube.extract_id(url) == want, (url, youtube.extract_id(url))
    ok("YouTube URL parsing (watch, youtu.be, shorts, mobile, rejects others)")

    tr = fake_transcript(300)
    raw = [{"start": 61.3, "end": 92.0, "title": "A", "hook": "x", "category": "hook", "score": 81, "reason": "r"},
           {"start": 150.0, "end": 400.0, "title": "B", "hook": "x", "category": "funny", "score": 90, "reason": "r"},
           {"start": 62.0, "end": 90.0, "title": "dup", "hook": "x", "category": "hook", "score": 50, "reason": "r"},
           {"start": 220.0, "end": 252.0, "title": "C", "hook": "x", "category": "educational", "score": 70, "reason": "r"}]
    picks = ai.finalize_clips(raw, tr, count=3, target_s=30, duration=300)
    assert [p["title"] for p in picks] == ["B", "A", "C"], picks
    for p in picks:
        assert 22.5 <= p["end"] - p["start"] <= 38, p
        assert any(abs(w["start"] - (p["start"] + 0.12)) < 0.01 for w in tr["words"]), "start not on a word"
    ok("Clip snapping: word-aligned starts, length limits, overlap removed, ranked by score")

    print("End-to-end (real FFmpeg, real HTTP)")
    src = tmp / "my-5-minute-video.mp4"
    make_video(src)
    ok(f"made 5:00 test video ({src.stat().st_size // 1024} KB)")

    server = subprocess.Popen([sys.executable, "-m", "uvicorn", "app.main:app", "--port", str(PORT), "--log-level", "warning"],
                              cwd=ROOT, env=os.environ.copy())
    try:
        for _ in range(50):
            try:
                requests.get(f"{BASE}/api/health", timeout=1); break
            except requests.ConnectionError:
                time.sleep(0.2)

        r = requests.post(f"{BASE}/api/projects", params={"filename": src.name, "length": 30}, data=b"x")
        assert r.status_code == 400 and "permission" in r.json()["error"]; ok("upload refused without rights confirmation")
        r = requests.post(f"{BASE}/api/projects", params={"filename": "a.mp4", "rights": 1}, data=b"not a video at all")
        assert r.status_code == 400; ok("non-video upload rejected")

        with src.open("rb") as fh:
            r = requests.post(f"{BASE}/api/projects", data=fh, params={
                "filename": src.name, "rights": 1, "length": 30, "count": 3, "aspect": "9:16",
                "caption_style": "Creator Bold", "category": "Podcast"})
        assert r.status_code == 201, r.text
        pid = r.json()["project_id"]; ok(f"uploaded → project {pid}, job queued")

        # Run the same pipeline the worker runs, with the two provider calls stubbed.
        conn = db.connect()
        job = db.claim_job(conn, "test")
        t0 = time.time()
        pipeline.run(conn, job, transcribe_fn=lambda chunks, lang: (
            [c.exists() and c.stat().st_size > 1000 for c, _ in chunks] and tr),
            analyse_fn=lambda t, **k: raw)
        ok(f"pipeline finished in {time.time() - t0:.1f}s")

        p = requests.get(f"{BASE}/api/projects/{pid}").json()
        assert p["status"] == "ready", p["job"]
        seen = [e["stage"] for e in p["events"]]
        assert seen[0] == "validating" and seen[-1] == "completed", seen
        ok("stages recorded: " + " → ".join(dict.fromkeys(seen)))
        assert len(p["clips"]) == 3

        out = tmp / "downloads"; out.mkdir()
        for c in p["clips"]:
            v = requests.get(BASE + c["video_url"], headers={"Range": "bytes=0-99"})
            assert v.status_code == 206 and len(v.content) == 100, v.status_code
            d = requests.get(BASE + c["download_url"])
            assert d.status_code == 200 and "attachment" in d.headers["content-disposition"]
            f = out / f"clip{c['rank']}.mp4"; f.write_bytes(d.content)
            info = media.probe(f)
            assert (info["width"], info["height"]) == (1080, 1920) and info["has_audio"], info
            assert abs(info["duration"] - c["duration"]) < 0.6, (info["duration"], c["duration"])
            t = requests.get(BASE + c["thumb_url"]); assert t.status_code == 200
            ok(f"clip {c['rank']} '{c['title']}' {c['start']:.1f}-{c['end']:.1f}s → 1080x1920 MP4, "
               f"{info['duration']:.1f}s, {len(d.content)//1024} KB, preview seeks (206), downloads, thumbnail")
        shutil.copytree(out, ROOT / "tests" / "output", dirs_exist_ok=True)

        bad = p["clips"][0]["video_url"][:-3] + "AAA"
        assert requests.get(BASE + bad).status_code == 403; ok("tampered media link refused")
        s = requests.get(f"{BASE}/api/stats").json()
        assert s["clips"] == 3 and s["downloads"] == 3, s; ok(f"stats are real counts: {s}")
    finally:
        server.terminate()
    print("\nAll checks passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
