"""The clipping pipeline. Every stage recorded here is real work; nothing is simulated."""
import json
import shutil
import time
from pathlib import Path

from . import ai, config, db, media


class StageError(Exception):
    def __init__(self, stage: str, message: str):
        super().__init__(message)
        self.stage = stage


def run(conn, job: dict, transcribe_fn=ai.transcribe, analyse_fn=ai.analyse) -> None:
    pid, jid = job["project_id"], job["id"]
    project = dict(conn.execute("SELECT * FROM projects WHERE id=?", (pid,)).fetchone())
    settings = json.loads(project["settings"])
    src = config.MEDIA_DIR / project["source_path"]
    pdir = src.parent
    work = pdir / "work"
    clips_dir = pdir / "clips"
    stage = "validating"

    def step(name: str, detail: str | None = None):
        nonlocal stage
        stage = name
        db.set_stage(conn, jid, name, detail)

    try:
        # 1. Validate
        step("validating")
        media.require_ffmpeg()
        if not project["rights_confirmed"]:
            raise media.MediaError("Rights confirmation is missing for this upload.")
        if not src.exists():
            raise media.MediaError("The uploaded file is missing from storage. Upload it again.")
        info = media.probe(src)
        if not info["has_video"]:
            raise media.MediaError("This file has no video track.")
        if not info["has_audio"]:
            raise media.MediaError("This video has no audio track, so there is no speech to analyse.")
        if info["duration"] < config.MIN_DURATION_S:
            raise media.MediaError(f"The video is {info['duration']:.0f} s long. Upload at least {config.MIN_DURATION_S} s.")
        if info["duration"] > config.MAX_DURATION_S:
            raise media.MediaError(f"The video is longer than the {config.MAX_DURATION_S // 60}-minute limit.")
        with db.tx(conn):
            conn.execute("UPDATE projects SET duration=?, width=?, height=? WHERE id=?",
                         (info["duration"], info["width"], info["height"], pid))

        # 2. Prepare a clean working area (a retry starts from scratch)
        step("preparing", f"{info['width']}×{info['height']}, {info['duration']:.0f} s")
        shutil.rmtree(work, ignore_errors=True)
        shutil.rmtree(clips_dir, ignore_errors=True)
        work.mkdir(parents=True)
        clips_dir.mkdir(parents=True)
        with db.tx(conn):
            conn.execute("DELETE FROM clips WHERE project_id=?", (pid,))

        # 3. Extract audio
        step("extracting_audio")
        chunks = media.extract_audio(src, work, info["duration"])

        # 4. Transcribe
        step("transcribing", f"{len(chunks)} audio part{'s' if len(chunks) > 1 else ''}")
        transcript = transcribe_fn(chunks, settings.get("language"))
        with db.tx(conn):
            conn.execute("INSERT OR REPLACE INTO transcripts (project_id,provider,language,data,created_at) VALUES (?,?,?,?,?)",
                         (pid, config.TRANSCRIBE_MODEL, transcript.get("language"), json.dumps(transcript), time.time()))
        for p, _ in chunks:
            p.unlink(missing_ok=True)

        # 5. Analyse
        count, target = int(settings["count"]), int(settings["length"])
        step("analysing", f"{len(transcript['words'])} words")
        raw = analyse_fn(transcript, count=count, target_s=target, category=settings["category"], duration=info["duration"])

        # 6. Generate clip boundaries from the AI picks
        step("generating_clips", f"{len(raw)} candidates")
        picks = ai.finalize_clips(raw, transcript, count=count, target_s=target, duration=info["duration"])
        if not picks:
            raise ai.ProviderError("No moments fit the chosen clip length. Try a different length.")
        now = time.time()
        rows = []
        with db.tx(conn):
            for rank, c in enumerate(picks, 1):
                cid = db.new_id()
                rows.append((cid, rank, c))
                conn.execute(
                    'INSERT INTO clips (id,project_id,rank,title,reason,category,hook,score,start,"end",aspect,created_at)'
                    " VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                    (cid, pid, rank, c["title"], c.get("reason"), c.get("category"), c.get("hook"), c["score"],
                     c["start"], c["end"], settings["aspect"], now))

        # 7. Captions
        tw, th = media.ASPECTS[settings["aspect"]]
        cap_paths = {}
        if settings.get("captions", True):
            step("adding_captions", settings.get("caption_style"))
            for cid, rank, c in rows:
                p = clips_dir / f"clip_{rank}.ass"
                media.write_captions(transcript["words"], c["start"], c["end"], p, tw, th, settings.get("caption_style", "Creator Bold"))
                cap_paths[cid] = p

        # 8. Render
        for i, (cid, rank, c) in enumerate(rows, 1):
            step("rendering", f"Clip {i} of {len(rows)}")
            out = clips_dir / f"clip_{rank}.mp4"
            media.render_clip(src, c["start"], c["end"], out, settings["aspect"], settings.get("fit", "crop"), cap_paths.get(cid))
            thumb = clips_dir / f"clip_{rank}.jpg"
            media.thumbnail(out, thumb)
            rel = lambda p: str(p.relative_to(config.MEDIA_DIR))
            with db.tx(conn):
                conn.execute("UPDATE clips SET file_path=?, thumb_path=?, caption_path=?, size_bytes=? WHERE id=?",
                             (rel(out), rel(thumb), rel(cap_paths[cid]) if cid in cap_paths else None, out.stat().st_size, cid))

        shutil.rmtree(work, ignore_errors=True)
        step("completed", f"{len(rows)} clips")
        db.finish_job(conn, jid, pid, ok=True)
    except (media.MediaError, ai.ProviderError) as e:
        db.finish_job(conn, jid, pid, ok=False, error=f"{stage}: {e}")
    except Exception as e:  # unexpected bug: keep the stage so support can find it
        db.finish_job(conn, jid, pid, ok=False, error=f"{stage}: Unexpected error ({type(e).__name__}: {e})")
        raise
