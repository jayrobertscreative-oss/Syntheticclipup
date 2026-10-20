"""Speech-to-text and highlight analysis. All provider calls happen server-side."""
import json
from pathlib import Path

import requests

from . import config


class ProviderError(Exception):
    """A provider is missing, misconfigured or returned something unusable."""


# ---------- transcription (OpenAI audio API) ----------

def transcribe(chunks: list[tuple[Path, float]], language: str | None) -> dict:
    """Return {"language", "words": [{word,start,end}], "segments": [{text,start,end}]} with absolute times."""
    if not config.OPENAI_API_KEY:
        raise ProviderError("Speech-to-text isn't configured. Set OPENAI_API_KEY on the server.")
    words, segments, lang = [], [], None
    for path, offset in chunks:
        data = {"model": config.TRANSCRIBE_MODEL, "response_format": "verbose_json",
                "timestamp_granularities[]": ["word", "segment"]}
        if language and language != "auto":
            data["language"] = language
        with path.open("rb") as fh:
            r = requests.post(
                "https://api.openai.com/v1/audio/transcriptions",
                headers={"Authorization": f"Bearer {config.OPENAI_API_KEY}"},
                data=data, files={"file": (path.name, fh, "audio/mpeg")}, timeout=900,
            )
        if r.status_code != 200:
            raise ProviderError(f"Transcription failed ({r.status_code}): {_err_text(r)}")
        body = r.json()
        lang = lang or body.get("language")
        for w in body.get("words", []):
            words.append({"word": w["word"], "start": float(w["start"]) + offset, "end": float(w["end"]) + offset})
        for s in body.get("segments", []):
            segments.append({"text": s["text"].strip(), "start": float(s["start"]) + offset, "end": float(s["end"]) + offset})
    if not words:
        raise ProviderError("No speech was detected in this video, so there is nothing to clip from.")
    return {"language": lang, "words": words, "segments": segments}


def _err_text(r: requests.Response) -> str:
    try:
        j = r.json()
        return (j.get("error") or {}).get("message") or json.dumps(j)[:300]
    except ValueError:
        return r.text[:300]


# ---------- highlight analysis (Claude) ----------

CLIP_TOOL = {
    "name": "submit_clips",
    "description": "Submit the recommended clips, best first.",
    "input_schema": {
        "type": "object",
        "properties": {
            "clips": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "start": {"type": "number", "description": "Start time in seconds, taken from a transcript line start."},
                        "end": {"type": "number", "description": "End time in seconds, taken from a transcript line end."},
                        "title": {"type": "string", "description": "Short social title, max 60 characters, no clickbait claims the clip doesn't support."},
                        "hook": {"type": "string", "description": "The opening line of the clip as spoken, quoted from the transcript."},
                        "category": {"type": "string", "enum": ["hook", "funny", "emotional", "conversation", "gaming", "podcast", "educational", "surprising"]},
                        "score": {"type": "integer", "minimum": 0, "maximum": 100, "description": "Estimated short-form engagement potential."},
                        "reason": {"type": "string", "description": "One or two sentences on why this moment works, referring to what is said."},
                    },
                    "required": ["start", "end", "title", "hook", "category", "score", "reason"],
                },
            }
        },
        "required": ["clips"],
    },
}

SYSTEM = """You are the highlight editor for Synthetic Clip Up, which turns long videos into short vertical clips.
You only see a timestamped transcript. Pick moments that work on their own for viewers who never saw the full video.
Look for: strong opening hooks, funny moments, emotional reactions, interesting exchanges, gaming highlights,
podcast highlights, clear educational explanations and surprising statements.
Rules:
- Start each clip at the beginning of a sentence and end it where a thought completes. Never start mid-sentence.
- Use timestamps that appear in the transcript lines. Do not invent times.
- Keep each clip within the requested length range.
- Clips must not overlap.
- Titles and reasons must only describe what is actually said. No invented facts or misleading claims.
- The score is an estimate of short-form potential, not a prediction of views."""


def _fmt(t: float) -> str:
    return f"{t:.1f}"


def analyse(transcript: dict, *, count: int, target_s: int, category: str, duration: float) -> list[dict]:
    if not config.ANTHROPIC_API_KEY:
        raise ProviderError("Highlight analysis isn't configured. Set ANTHROPIC_API_KEY on the server.")
    lo, hi = target_s * 0.75, target_s * 1.25
    lines = "\n".join(f"[{_fmt(s['start'])}-{_fmt(s['end'])}] {s['text']}" for s in transcript["segments"])
    user = (f"Video length: {duration:.0f} s. Content type: {category}.\n"
            f"Return up to {count + 2} clip candidates, each {lo:.0f}-{hi:.0f} seconds long (target {target_s} s), best first.\n\n"
            f"Transcript (seconds):\n{lines}")
    r = requests.post(
        "https://api.anthropic.com/v1/messages",
        headers={"x-api-key": config.ANTHROPIC_API_KEY, "anthropic-version": "2023-06-01", "content-type": "application/json"},
        json={"model": config.CLAUDE_MODEL, "max_tokens": 4000, "system": SYSTEM,
              "tools": [CLIP_TOOL], "tool_choice": {"type": "tool", "name": "submit_clips"},
              "messages": [{"role": "user", "content": user}]},
        timeout=300,
    )
    if r.status_code != 200:
        raise ProviderError(f"Highlight analysis failed ({r.status_code}): {_err_text(r)}")
    for block in r.json().get("content", []):
        if block.get("type") == "tool_use" and block.get("name") == "submit_clips":
            return block["input"].get("clips", [])
    raise ProviderError("Highlight analysis returned no clips.")


# ---------- boundary snapping (pure, unit-testable) ----------

def finalize_clips(raw: list[dict], transcript: dict, *, count: int, target_s: int, duration: float) -> list[dict]:
    """Snap AI picks to real word boundaries, enforce length, drop overlaps, rank."""
    words, segs = transcript["words"], transcript["segments"]
    lo, hi = max(8.0, target_s * 0.75), target_s * 1.25
    picked: list[dict] = []
    for c in sorted(raw, key=lambda c: -int(c.get("score", 0))):
        try:
            s, e = float(c["start"]), float(c["end"])
        except (KeyError, TypeError, ValueError):
            continue
        s, e = max(0.0, s), min(duration, e)
        first = next((w for w in words if w["start"] >= s - 0.3), None)
        if not first:
            continue
        s = first["start"]
        # Never cut a word in half at the end; trim to the last whole word inside the max length.
        e = min(e, s + hi)
        last = [w for w in words if w["end"] <= e + 0.3 and w["start"] >= s]
        if not last:
            continue
        e = last[-1]["end"]
        if e - s < lo:
            # Extend to following sentence ends until long enough, within the max.
            for seg in segs:
                if seg["end"] > e and seg["end"] - s <= hi:
                    e = seg["end"]
                    if e - s >= lo:
                        break
        if not (lo <= e - s <= hi + 0.3):
            continue
        s, e = max(0.0, s - 0.12), min(duration, e + 0.3)
        if any(min(e, p["end"]) - max(s, p["start"]) > 1.0 for p in picked):
            continue
        picked.append({**c, "start": round(s, 3), "end": round(e, 3),
                       "score": max(0, min(100, int(c.get("score", 0)))),
                       "title": str(c.get("title", "Untitled clip"))[:80]})
        if len(picked) >= count:
            break
    return picked
