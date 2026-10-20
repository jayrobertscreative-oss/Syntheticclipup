"""Server-side settings. Every secret is read from the environment and never sent to the browser."""
import os
import secrets
from pathlib import Path


def _load_dotenv(path: Path) -> None:
    """Minimal .env loader so local runs need no extra packages."""
    if not path.exists():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


ROOT = Path(__file__).resolve().parent.parent
_load_dotenv(ROOT / ".env")

DATA_DIR = Path(os.environ.get("SCU_DATA_DIR", ROOT / "data")).resolve()
MEDIA_DIR = DATA_DIR / "media"          # private: never served statically
DB_PATH = DATA_DIR / "scu.sqlite3"

# Signing key for short-lived media URLs. Set SCU_SECRET in production so links survive restarts.
SECRET = os.environ.get("SCU_SECRET") or secrets.token_hex(32)
MEDIA_URL_TTL = int(os.environ.get("SCU_MEDIA_URL_TTL", "3600"))

# Optional shared key that gates the whole API until real accounts arrive in Phase 2.
ACCESS_KEY = os.environ.get("SCU_ACCESS_KEY", "")

MAX_UPLOAD_BYTES = int(os.environ.get("SCU_MAX_UPLOAD_MB", "2048")) * 1024 * 1024
MIN_DURATION_S = 20
MAX_DURATION_S = int(os.environ.get("SCU_MAX_DURATION_MIN", "180")) * 60

# Providers
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "")
TRANSCRIBE_MODEL = os.environ.get("SCU_TRANSCRIBE_MODEL", "whisper-1")
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
CLAUDE_MODEL = os.environ.get("SCU_CLAUDE_MODEL", "claude-sonnet-5-5")
YOUTUBE_API_KEY = os.environ.get("YOUTUBE_API_KEY", "")

WORKER_POLL_S = float(os.environ.get("SCU_WORKER_POLL_S", "2"))
STALE_JOB_S = int(os.environ.get("SCU_STALE_JOB_S", "7200"))

MEDIA_DIR.mkdir(parents=True, exist_ok=True)
