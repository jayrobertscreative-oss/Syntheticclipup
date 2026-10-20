"""SQLite storage for projects, processing jobs, stage events and clips.

SQLite keeps the first version zero-setup. The schema maps 1:1 to the Postgres
entities in the masterplan, so moving to Postgres in Phase 2 is a driver swap.
"""
import json
import sqlite3
import time
import uuid
from contextlib import contextmanager

from . import config

STAGES = [
    ("validating", "Validating source"),
    ("preparing", "Preparing video"),
    ("extracting_audio", "Extracting audio"),
    ("transcribing", "Transcribing speech"),
    ("analysing", "Analysing highlights"),
    ("generating_clips", "Generating clips"),
    ("adding_captions", "Adding captions"),
    ("rendering", "Rendering"),
    ("completed", "Completed"),
]

SCHEMA = """
CREATE TABLE IF NOT EXISTS projects (
  id TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  created_at REAL NOT NULL,
  source_type TEXT NOT NULL,            -- upload | youtube (future, permitted sources only)
  source_path TEXT,                     -- relative to MEDIA_DIR
  source_size INTEGER,
  rights_confirmed INTEGER NOT NULL DEFAULT 0,
  settings TEXT NOT NULL,               -- JSON
  duration REAL, width INTEGER, height INTEGER,
  status TEXT NOT NULL                  -- queued | processing | ready | failed
);
CREATE TABLE IF NOT EXISTS jobs (
  id TEXT PRIMARY KEY,
  project_id TEXT NOT NULL REFERENCES projects(id),
  status TEXT NOT NULL,                 -- queued | running | completed | failed
  stage TEXT, detail TEXT, error TEXT,
  attempts INTEGER NOT NULL DEFAULT 0,
  worker TEXT,
  created_at REAL NOT NULL, started_at REAL, heartbeat_at REAL, finished_at REAL
);
CREATE TABLE IF NOT EXISTS job_events (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  job_id TEXT NOT NULL REFERENCES jobs(id),
  stage TEXT NOT NULL, detail TEXT, at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS transcripts (
  project_id TEXT PRIMARY KEY REFERENCES projects(id),
  provider TEXT NOT NULL, language TEXT, data TEXT NOT NULL, created_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS clips (
  id TEXT PRIMARY KEY,
  project_id TEXT NOT NULL REFERENCES projects(id),
  rank INTEGER NOT NULL,
  title TEXT NOT NULL, reason TEXT, category TEXT, hook TEXT,
  score INTEGER,
  start REAL NOT NULL, "end" REAL NOT NULL,
  aspect TEXT NOT NULL,
  file_path TEXT, thumb_path TEXT, caption_path TEXT,
  size_bytes INTEGER, downloads INTEGER NOT NULL DEFAULT 0,
  created_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs(status, created_at);
CREATE INDEX IF NOT EXISTS idx_clips_project ON clips(project_id, rank);
CREATE INDEX IF NOT EXISTS idx_events_job ON job_events(job_id, id);
"""


def connect() -> sqlite3.Connection:
    conn = sqlite3.connect(config.DB_PATH, timeout=30, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


@contextmanager
def tx(conn: sqlite3.Connection):
    """Write transaction that takes the lock up front, so job claims are atomic."""
    conn.execute("BEGIN IMMEDIATE")
    try:
        yield conn
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise


def init() -> None:
    with connect() as conn:
        conn.executescript(SCHEMA)


def new_id() -> str:
    return uuid.uuid4().hex[:16]


def create_project(conn, *, name, source_path, source_size, settings, rights_confirmed) -> tuple[str, str]:
    pid, jid, now = new_id(), new_id(), time.time()
    with tx(conn):
        conn.execute(
            "INSERT INTO projects (id,name,created_at,source_type,source_path,source_size,rights_confirmed,settings,status)"
            " VALUES (?,?,?,?,?,?,?,?,?)",
            (pid, name, now, "upload", source_path, source_size, int(rights_confirmed), json.dumps(settings), "queued"),
        )
        conn.execute(
            "INSERT INTO jobs (id,project_id,status,stage,created_at) VALUES (?,?,?,?,?)",
            (jid, pid, "queued", None, now),
        )
    return pid, jid


def claim_job(conn, worker: str):
    now = time.time()
    with tx(conn):
        # Requeue jobs whose worker died mid-run.
        conn.execute(
            "UPDATE jobs SET status='queued', worker=NULL WHERE status='running' AND heartbeat_at < ? AND attempts < 3",
            (now - config.STALE_JOB_S,),
        )
        row = conn.execute("SELECT * FROM jobs WHERE status='queued' ORDER BY created_at LIMIT 1").fetchone()
        if not row:
            return None
        conn.execute(
            "UPDATE jobs SET status='running', worker=?, attempts=attempts+1, started_at=?, heartbeat_at=?, error=NULL WHERE id=?",
            (worker, now, now, row["id"]),
        )
        conn.execute("UPDATE projects SET status='processing' WHERE id=?", (row["project_id"],))
    return dict(row)


def set_stage(conn, job_id: str, stage: str, detail: str | None = None) -> None:
    now = time.time()
    with tx(conn):
        conn.execute("UPDATE jobs SET stage=?, detail=?, heartbeat_at=? WHERE id=?", (stage, detail, now, job_id))
        conn.execute("INSERT INTO job_events (job_id,stage,detail,at) VALUES (?,?,?,?)", (job_id, stage, detail, now))


def finish_job(conn, job_id: str, project_id: str, ok: bool, error: str | None = None) -> None:
    now = time.time()
    with tx(conn):
        conn.execute(
            "UPDATE jobs SET status=?, error=?, finished_at=?, heartbeat_at=? WHERE id=?",
            ("completed" if ok else "failed", error, now, now, job_id),
        )
        conn.execute("UPDATE projects SET status=? WHERE id=?", ("ready" if ok else "failed", project_id))
