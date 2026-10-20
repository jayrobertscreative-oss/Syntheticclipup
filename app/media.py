"""FFmpeg/ffprobe wrappers: probing, audio extraction, caption files, clip rendering."""
import json
import math
import shutil
import subprocess
from pathlib import Path

ASPECTS = {"9:16": (1080, 1920), "1:1": (1080, 1080), "16:9": (1920, 1080)}

# Whisper-style APIs cap uploads at 25 MB. Mono 16 kHz MP3 at 48 kbps is ~0.36 MB/min,
# so 20-minute chunks stay well under the limit.
AUDIO_CHUNK_S = 20 * 60


class MediaError(Exception):
    """A user-facing media problem (bad file, missing stream, FFmpeg failure)."""


def require_ffmpeg() -> None:
    for tool in ("ffmpeg", "ffprobe"):
        if not shutil.which(tool):
            raise MediaError(f"{tool} is not installed on the server.")


def _run(cmd: list[str], cwd: Path | None = None, timeout: int = 3600) -> str:
    proc = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=timeout)
    if proc.returncode != 0:
        tail = "\n".join(proc.stderr.strip().splitlines()[-6:])
        raise MediaError(f"FFmpeg failed: {tail or 'unknown error'}")
    return proc.stdout


def probe(path: Path) -> dict:
    out = _run(["ffprobe", "-v", "error", "-print_format", "json", "-show_format", "-show_streams", str(path)], timeout=120)
    data = json.loads(out or "{}")
    streams = data.get("streams", [])
    video = next((s for s in streams if s.get("codec_type") == "video" and s.get("disposition", {}).get("attached_pic") != 1), None)
    audio = next((s for s in streams if s.get("codec_type") == "audio"), None)
    duration = float(data.get("format", {}).get("duration") or (video or {}).get("duration") or 0)
    w, h = (int(video["width"]), int(video["height"])) if video else (0, 0)
    # Phones store portrait video as landscape pixels plus a rotation flag.
    rot = 0
    for sd in (video or {}).get("side_data_list", []) or []:
        if "rotation" in sd:
            rot = int(float(sd["rotation"]))
    rot = rot or int((video or {}).get("tags", {}).get("rotate", 0) or 0)
    if abs(rot) % 180 == 90:
        w, h = h, w
    return {"duration": duration, "width": w, "height": h, "has_video": bool(video), "has_audio": bool(audio),
            "format": data.get("format", {}).get("format_name", "")}


def extract_audio(src: Path, workdir: Path, duration: float) -> list[tuple[Path, float]]:
    """Return [(audio_chunk_path, offset_seconds)]."""
    chunks = []
    n = max(1, math.ceil(duration / AUDIO_CHUNK_S))
    for i in range(n):
        offset = i * AUDIO_CHUNK_S
        out = workdir / f"audio_{i:02d}.mp3"
        _run(["ffmpeg", "-y", "-v", "error", "-ss", str(offset), "-i", str(src), "-t", str(AUDIO_CHUNK_S),
              "-vn", "-ac", "1", "-ar", "16000", "-c:a", "libmp3lame", "-b:a", "48k", str(out)])
        if out.stat().st_size > 24 * 1024 * 1024:
            raise MediaError("Extracted audio chunk exceeded the transcription size limit.")
        chunks.append((out, float(offset)))
    return chunks


# ---------- captions (ASS, burned in by libass) ----------

def _ass_time(t: float) -> str:
    t = max(0.0, t)
    h, rem = divmod(t, 3600)
    m, s = divmod(rem, 60)
    return f"{int(h)}:{int(m):02d}:{s:05.2f}"


def _ass_escape(text: str) -> str:
    return text.replace("\\", "").replace("{", "(").replace("}", ")").replace("\n", " ")


CAPTION_STYLES = {
    # name: (font size as fraction of height, primary &HBBGGRR, highlight, outline px, uppercase)
    "Creator Bold": (0.046, "&H00FFFFFF", "&H00FFC836", 6, True),   # highlight = electric blue #36C8FF
    "Purple Pulse": (0.048, "&H00FFFFFF", "&H00FF5678", 5, False),  # highlight = electric purple #7856FF
    "Gaming Energy": (0.058, "&H0000F0FF", "&H00FFFFFF", 7, True),
    "Podcast Clean": (0.040, "&H00FFFFFF", "&H00FFFFFF", 3, False),
    "Minimal": (0.036, "&H00FFFFFF", "&H00FFFFFF", 2, False),
    "Cinematic": (0.040, "&H00E6F0FF", "&H00FFFFFF", 2, False),
}


def write_captions(words: list[dict], clip_start: float, clip_end: float, out: Path,
                   width: int, height: int, style: str = "Creator Bold") -> int:
    """Write an .ass file for one clip; words are absolute-timed. Returns caption events written."""
    size_frac, primary, highlight, outline, upper = CAPTION_STYLES.get(style, CAPTION_STYLES["Creator Bold"])
    font_size = int(height * size_frac) if height >= width else int(height * size_frac * 1.5)
    margin_v = int(height * (0.22 if height > width else 0.10))
    header = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {width}
PlayResY: {height}
WrapStyle: 0
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: SCU,DejaVu Sans,{font_size},{primary},{primary},&H00000000,&H64000000,1,0,0,0,100,100,0,0,1,{outline},2,2,{int(width*0.08)},{int(width*0.08)},{margin_v},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    inside = [w for w in words if w["end"] > clip_start and w["start"] < clip_end]
    # Group into short on-screen phrases of up to 3 words, breaking on long pauses.
    groups, cur = [], []
    for w in inside:
        if cur and (len(cur) >= 3 or w["start"] - cur[-1]["end"] > 0.6):
            groups.append(cur)
            cur = []
        cur.append(w)
    if cur:
        groups.append(cur)

    lines = []
    for gi, g in enumerate(groups):
        g_end = g[-1]["end"]
        nxt = groups[gi + 1][0]["start"] if gi + 1 < len(groups) else None
        if nxt is not None and nxt - g_end < 0.6:
            g_end = nxt  # hold the phrase on screen through short gaps so captions don't flicker
        g_end = min(g_end, clip_end)
        for i, w in enumerate(g):
            s = max(w["start"], clip_start) - clip_start
            e = (g[i + 1]["start"] if i + 1 < len(g) else g_end) - clip_start
            if e - s < 0.05:
                continue
            parts = []
            for j, x in enumerate(g):
                t = _ass_escape(x["word"].strip())
                t = t.upper() if upper else t
                parts.append("{\\c" + highlight + "}" + t + "{\\c" + primary + "}" if j == i else t)
            lines.append(f"Dialogue: 0,{_ass_time(s)},{_ass_time(e)},SCU,,0,0,0,,{' '.join(parts)}")
    out.write_text(header + "\n".join(lines) + "\n", encoding="utf-8")
    return len(lines)


# ---------- rendering ----------

def _frame_filter(aspect: str, fit: str) -> str:
    tw, th = ASPECTS[aspect]
    if fit == "pad":
        return (f"scale={tw}:{th}:force_original_aspect_ratio=decrease,"
                f"pad={tw}:{th}:(ow-iw)/2:(oh-ih)/2:color=0x0B0B12,setsar=1")
    # Centre crop to the target ratio, then scale. Face tracking replaces this in Phase 6.
    r = f"{tw}/{th}"
    return (f"crop='if(gt(iw/ih,{r}),ih*{r},iw)':'if(gt(iw/ih,{r}),ih,iw/({r}))',"
            f"scale={tw}:{th},setsar=1")


def render_clip(src: Path, start: float, end: float, out: Path, aspect: str, fit: str,
                captions: Path | None) -> dict:
    vf = _frame_filter(aspect, fit)
    if captions is not None:
        vf += f",setpts=PTS-STARTPTS,subtitles={captions.name}"   # relative name: run with cwd=captions dir to avoid path escaping
    _run(["ffmpeg", "-y", "-v", "error", "-ss", f"{start:.3f}", "-i", str(src.resolve()), "-t", f"{end - start:.3f}",
          "-map", "0:v:0", "-map", "0:a:0?", "-vf", vf,
          "-c:v", "libx264", "-preset", "veryfast", "-crf", "21", "-pix_fmt", "yuv420p",
          "-c:a", "aac", "-b:a", "128k", "-ar", "48000", "-movflags", "+faststart", str(out.resolve())],
         cwd=(captions.parent if captions is not None else out.parent), timeout=1800)
    info = probe(out)
    if not info["has_video"] or info["duration"] < 1:
        raise MediaError("Rendered clip was empty.")
    return info


def thumbnail(clip: Path, out: Path) -> None:
    _run(["ffmpeg", "-y", "-v", "error", "-ss", "0.8", "-i", str(clip), "-frames:v", "1", "-vf", "scale=360:-2", "-q:v", "4", str(out)])
