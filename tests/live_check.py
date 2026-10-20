"""Check your real API keys against one of your own videos, without the web app.

Usage:  python tests/live_check.py path/to/your-video.mp4

Prints the transcript size and the clips Claude picks. Costs a few pence of API usage.
"""
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app import ai, config, media  # noqa: E402


def main(path: str) -> None:
    src = Path(path)
    print(f"Speech-to-text key set: {bool(config.OPENAI_API_KEY)} · Claude key set: {bool(config.ANTHROPIC_API_KEY)} · model {config.CLAUDE_MODEL}")
    info = media.probe(src)
    print(f"Video: {info['duration']:.0f} s, {info['width']}x{info['height']}, audio: {info['has_audio']}")
    with tempfile.TemporaryDirectory() as tmp:
        chunks = media.extract_audio(src, Path(tmp), info["duration"])
        tr = ai.transcribe(chunks, None)
    print(f"Transcript: {len(tr['words'])} words, {len(tr['segments'])} sentences, language {tr['language']}")
    raw = ai.analyse(tr, count=3, target_s=30, category="General", duration=info["duration"])
    picks = ai.finalize_clips(raw, tr, count=3, target_s=30, duration=info["duration"])
    for i, c in enumerate(picks, 1):
        print(f"\n#{i}  {c['start']:.1f}-{c['end']:.1f}s  score {c['score']}  [{c['category']}]\n    {c['title']}\n    {c['reason']}")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    main(sys.argv[1])
