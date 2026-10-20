"""HTTP API and the Synthetic Clip Up web app.

Run:  uvicorn app.main:app --host 127.0.0.1 --port 8000
"""
import base64
import hashlib
import hmac
import json
import re
import time

from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import FileResponse, JSONResponse, Response
from starlette.routing import Mount, Route
from starlette.staticfiles import StaticFiles

from . import config, db, media, youtube

ALLOWED_EXT = {".mp4", ".mov", ".m4v"}
LENGTHS = {15, 30, 45, 60}


def err(status: int, message: str) -> JSONResponse:
    return JSONResponse({"error": message}, status_code=status)


# ---------- signed media URLs ----------

def _sign(payload: bytes) -> str:
    return base64.urlsafe_b64encode(hmac.new(config.SECRET.encode(), payload, hashlib.sha256).digest()[:18]).decode().rstrip("=")


def media_url(rel_path: str | None, download_name: str | None = None) -> str | None:
    if not rel_path:
        return None
    body = json.dumps({"p": rel_path, "x": int(time.time()) + config.MEDIA_URL_TTL, "d": download_name}, separators=(",", ":")).encode()
    tok = base64.urlsafe_b64encode(body).decode().rstrip("=")
    return f"/media/{tok}.{_sign(body)}"


async def serve_media(request: Request):
    token = request.path_params["token"]
    try:
        tok, sig = token.rsplit(".", 1)
        body = base64.urlsafe_b64decode(tok + "=" * (-len(tok) % 4))
    except (ValueError, base64.binascii.Error):
        return err(404, "Not found")
    if not hmac.compare_digest(sig, _sign(body)):
        return err(403, "This link is invalid.")
    data = json.loads(body)
    if data["x"] < time.time():
        return err(403, "This link has expired. Reload the project to get a fresh one.")
    path = (config.MEDIA_DIR / data["p"]).resolve()
    if config.MEDIA_DIR not in path.parents or not path.is_file():
        return err(404, "Not found")
    if data.get("d") and request.headers.get("range") is None:
        conn = db.connect()
        with db.tx(conn):
            conn.execute("UPDATE clips SET downloads=downloads+1 WHERE file_path=?", (data["p"],))
    return FileResponse(path, filename=data.get("d"),
                        content_disposition_type="attachment" if data.get("d") else "inline",
                        headers={"Cache-Control": "private, max-age=600"})


# ---------- projects ----------

def _clean_settings(q) -> dict | str:
    try:
        length, count = int(q.get("length", 30)), int(q.get("count", 3))
    except ValueError:
        return "Clip length and number of clips must be numbers."
    s = {
        "length": length, "count": count,
        "aspect": q.get("aspect", "9:16"), "fit": q.get("fit", "crop"),
        "captions": q.get("captions", "1") == "1",
        "caption_style": q.get("caption_style", "Creator Bold"),
        "category": q.get("category", "General")[:40],
        "language": (q.get("language") or "auto")[:8],
    }
    if s["length"] not in LENGTHS:
        return "Clip length must be 15, 30, 45 or 60 seconds."
    if not 1 <= s["count"] <= 10:
        return "Number of clips must be between 1 and 10."
    if s["aspect"] not in media.ASPECTS:
        return "Aspect ratio must be 9:16, 1:1 or 16:9."
    if s["fit"] not in ("crop", "pad"):
        return "Framing must be crop or pad."
    if s["caption_style"] not in media.CAPTION_STYLES:
        return "Unknown caption style."
    return s


async def upload(request: Request):
    """Raw-body upload: the file is the request body, settings are query parameters.
    Streams straight to private storage and enforces the size limit while writing."""
    q = request.query_params
    if q.get("rights") != "1":
        return err(400, "Confirm that you own this video or have permission to process it.")
    name = re.sub(r"[^\w.\- ()]", "_", (q.get("filename") or "upload.mp4"))[:120]
    ext = ("." + name.rsplit(".", 1)[-1].lower()) if "." in name else ""
    if ext not in ALLOWED_EXT:
        return err(400, "Upload an MP4 or MOV file.")
    settings = _clean_settings(q)
    if isinstance(settings, str):
        return err(400, settings)
    declared = int(request.headers.get("content-length") or 0)
    if declared > config.MAX_UPLOAD_BYTES:
        return err(413, f"The file is larger than {config.MAX_UPLOAD_BYTES // 1024 // 1024} MB.")

    folder = db.new_id()
    dest_dir = config.MEDIA_DIR / folder
    dest_dir.mkdir(parents=True)
    dest = dest_dir / f"source{ext}"
    size, head = 0, b""
    try:
        with dest.open("wb") as fh:
            async for chunk in request.stream():
                size += len(chunk)
                if size > config.MAX_UPLOAD_BYTES:
                    raise ValueError("too_large")
                if len(head) < 12:
                    head += chunk[:12]
                fh.write(chunk)
    except ValueError:
        dest.unlink(missing_ok=True); dest_dir.rmdir()
        return err(413, f"The file is larger than {config.MAX_UPLOAD_BYTES // 1024 // 1024} MB.")
    if size == 0 or head[4:8] != b"ftyp":
        dest.unlink(missing_ok=True); dest_dir.rmdir()
        return err(400, "That file isn't a valid MP4 or MOV video.")

    conn = db.connect()
    title = (q.get("name") or name.rsplit(".", 1)[0])[:120]
    pid, jid = db.create_project(conn, name=title, source_path=f"{folder}/{dest.name}", source_size=size,
                                 settings=settings, rights_confirmed=True)
    return JSONResponse({"project_id": pid, "job_id": jid}, status_code=201)


def _project_payload(conn, pid: str) -> dict | None:
    p = conn.execute("SELECT * FROM projects WHERE id=?", (pid,)).fetchone()
    if not p:
        return None
    job = conn.execute("SELECT * FROM jobs WHERE project_id=? ORDER BY created_at DESC LIMIT 1", (pid,)).fetchone()
    events = conn.execute("SELECT stage, detail, at FROM job_events WHERE job_id=? ORDER BY id", (job["id"],)).fetchall() if job else []
    clips = conn.execute('SELECT * FROM clips WHERE project_id=? ORDER BY rank', (pid,)).fetchall()
    safe = re.sub(r"[^\w\-]+", "-", p["name"]).strip("-")[:40] or "clip"
    return {
        "id": p["id"], "name": p["name"], "created_at": p["created_at"], "status": p["status"],
        "duration": p["duration"], "width": p["width"], "height": p["height"], "size": p["source_size"],
        "settings": json.loads(p["settings"]),
        "job": {"status": job["status"], "stage": job["stage"], "detail": job["detail"], "error": job["error"],
                "attempts": job["attempts"]} if job else None,
        "events": [dict(e) for e in events],
        "stages": [{"key": k, "label": l} for k, l in db.STAGES],
        "clips": [{
            "id": c["id"], "rank": c["rank"], "title": c["title"], "reason": c["reason"], "category": c["category"],
            "hook": c["hook"], "score": c["score"], "start": c["start"], "end": c["end"],
            "duration": round(c["end"] - c["start"], 2), "aspect": c["aspect"], "size": c["size_bytes"],
            "video_url": media_url(c["file_path"]), "thumb_url": media_url(c["thumb_path"]),
            "download_url": media_url(c["file_path"], f"{safe}-clip-{c['rank']}.mp4"),
        } for c in clips if c["file_path"]],
    }


async def get_project(request: Request):
    data = _project_payload(db.connect(), request.path_params["pid"])
    return JSONResponse(data) if data else err(404, "Project not found.")


async def list_projects(request: Request):
    conn = db.connect()
    rows = conn.execute(
        "SELECT p.*, (SELECT COUNT(*) FROM clips c WHERE c.project_id=p.id AND c.file_path IS NOT NULL) AS n_clips,"
        " (SELECT thumb_path FROM clips c WHERE c.project_id=p.id ORDER BY rank LIMIT 1) AS thumb,"
        " (SELECT stage FROM jobs j WHERE j.project_id=p.id ORDER BY created_at DESC LIMIT 1) AS stage,"
        " (SELECT error FROM jobs j WHERE j.project_id=p.id ORDER BY created_at DESC LIMIT 1) AS error"
        " FROM projects p ORDER BY created_at DESC LIMIT 200").fetchall()
    return JSONResponse([{"id": r["id"], "name": r["name"], "created_at": r["created_at"], "status": r["status"],
                          "duration": r["duration"], "clips": r["n_clips"], "stage": r["stage"], "error": r["error"],
                          "thumb_url": media_url(r["thumb"])} for r in rows])


async def retry(request: Request):
    pid = request.path_params["pid"]
    conn = db.connect()
    with db.tx(conn):
        job = conn.execute("SELECT * FROM jobs WHERE project_id=? ORDER BY created_at DESC LIMIT 1", (pid,)).fetchone()
        if not job:
            return err(404, "Project not found.")
        if job["status"] != "failed":
            return err(409, "Only failed projects can be retried.")
        conn.execute("INSERT INTO jobs (id,project_id,status,created_at) VALUES (?,?,?,?)", (db.new_id(), pid, "queued", time.time()))
        conn.execute("UPDATE projects SET status='queued' WHERE id=?", (pid,))
    return JSONResponse({"ok": True})


async def stats(request: Request):
    conn = db.connect()
    one = lambda sql: conn.execute(sql).fetchone()[0]
    return JSONResponse({
        "projects": one("SELECT COUNT(*) FROM projects"),
        "clips": one("SELECT COUNT(*) FROM clips WHERE file_path IS NOT NULL"),
        "downloads": one("SELECT COALESCE(SUM(downloads),0) FROM clips"),
        "minutes": round(one("SELECT COALESCE(SUM(duration),0) FROM projects WHERE status='ready'") / 60, 1),
        "failed_jobs": one("SELECT COUNT(*) FROM jobs WHERE status='failed'"),
    })


async def activity(request: Request):
    conn = db.connect()
    rows = conn.execute(
        "SELECT j.status, j.error, j.finished_at, p.name, p.id,"
        " (SELECT COUNT(*) FROM clips c WHERE c.project_id=p.id AND c.file_path IS NOT NULL) AS n"
        " FROM jobs j JOIN projects p ON p.id=j.project_id WHERE j.finished_at IS NOT NULL"
        " ORDER BY j.finished_at DESC LIMIT 8").fetchall()
    return JSONResponse([dict(r) for r in rows])


async def inspect_youtube(request: Request):
    try:
        body = await request.json()
    except ValueError:
        return err(400, "Send JSON with a url field.")
    try:
        return JSONResponse(youtube.inspect(str(body.get("url", ""))))
    except Exception as e:  # network or API trouble
        return err(502, f"Couldn't reach YouTube: {e}")


async def health(request: Request):
    import shutil
    return JSONResponse({
        "ffmpeg": bool(shutil.which("ffmpeg")), "speech_to_text": bool(config.OPENAI_API_KEY),
        "analysis": bool(config.ANTHROPIC_API_KEY), "youtube_metadata": bool(config.YOUTUBE_API_KEY),
        "auth_required": bool(config.ACCESS_KEY),
        "queued": db.connect().execute("SELECT COUNT(*) FROM jobs WHERE status='queued'").fetchone()[0],
    })


async def index(request: Request):
    return FileResponse(config.ROOT / "static" / "index.html", headers={"Cache-Control": "no-cache"})


class AccessKey(BaseHTTPMiddleware):
    """Until Phase 2 accounts exist, an optional shared key keeps a deployed server private."""
    async def dispatch(self, request, call_next):
        p = request.url.path
        if config.ACCESS_KEY and p.startswith("/api/") and p != "/api/health":
            if not hmac.compare_digest(request.headers.get("x-scu-key", ""), config.ACCESS_KEY):
                return err(401, "Enter your Synthetic Clip Up access key.")
        resp: Response = await call_next(request)
        resp.headers.setdefault("X-Content-Type-Options", "nosniff")
        return resp


db.init()
app = Starlette(
    routes=[
        Route("/", index),
        Route("/api/health", health),
        Route("/api/stats", stats),
        Route("/api/activity", activity),
        Route("/api/projects", list_projects, methods=["GET"]),
        Route("/api/projects", upload, methods=["POST"]),
        Route("/api/projects/{pid}", get_project),
        Route("/api/projects/{pid}/retry", retry, methods=["POST"]),
        Route("/api/youtube/inspect", inspect_youtube, methods=["POST"]),
        Route("/media/{token}", serve_media),
        Mount("/static", StaticFiles(directory=config.ROOT / "static"), name="static"),
    ],
    middleware=[Middleware(AccessKey)],
)
