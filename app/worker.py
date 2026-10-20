"""Background worker. Run one or more of these alongside the web server:

    python -m app.worker
"""
import logging
import os
import socket
import time
import traceback

from . import config, db, pipeline

log = logging.getLogger("scu.worker")


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
    db.init()
    name = f"{socket.gethostname()}:{os.getpid()}"
    conn = db.connect()
    log.info("worker %s polling for jobs", name)
    while True:
        job = db.claim_job(conn, name)
        if not job:
            time.sleep(config.WORKER_POLL_S)
            continue
        log.info("job %s (project %s) started", job["id"], job["project_id"])
        try:
            pipeline.run(conn, job)
        except Exception:
            log.error("job %s crashed:\n%s", job["id"], traceback.format_exc())
        row = conn.execute("SELECT status, error FROM jobs WHERE id=?", (job["id"],)).fetchone()
        log.info("job %s finished: %s %s", job["id"], row["status"], row["error"] or "")


if __name__ == "__main__":
    main()
