"""Entry point used by each worker process: run one job if one is due."""
from jobqueue import db, jobs


def process_one(db_path, queue, worker, handler, *, now, lease_seconds=30.0):
    """Claim one job from ``queue``, run ``handler(payload)`` and record the outcome.

    Returns the id of the job that was run, or None if no job was due.
    """
    conn = db.connect(db_path)
    try:
        job = jobs.claim(conn, queue, worker, now=now, lease_seconds=lease_seconds)
        if job is None:
            return None
        try:
            result = handler(job.payload)
        except Exception as exc:  # the job's own failure is recorded, not raised
            jobs.fail(conn, job.id, job.lease_token, now=now, error=f"{type(exc).__name__}: {exc}")
        else:
            jobs.complete(conn, job.id, job.lease_token, now=now, result=result)
        return job.id
    finally:
        conn.close()
