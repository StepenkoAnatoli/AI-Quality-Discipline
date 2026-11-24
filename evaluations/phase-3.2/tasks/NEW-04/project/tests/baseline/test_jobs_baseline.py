import os
import shutil
import tempfile
import unittest

from jobqueue import db, jobs
from jobqueue.worker import process_one

T0 = 1_000_000.0


class JobsBaselineTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.path = os.path.join(self.tmp, "jobs.db")
        self.conn = db.connect(self.path)
        db.init_schema(self.conn)

    def tearDown(self):
        self.conn.close()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def state(self, job_id):
        return self.conn.execute("SELECT state FROM jobs WHERE id = ?", (job_id,)).fetchone()[0]

    def test_enqueue_then_claim_returns_the_job(self):
        job_id = jobs.enqueue(self.conn, "mail", {"to": "a@example.com"}, now=T0)
        job = jobs.claim(self.conn, "mail", "w1", now=T0, lease_seconds=30)
        self.assertEqual((job.id, job.queue, job.payload, job.attempts), (job_id, "mail", {"to": "a@example.com"}, 1))
        self.assertEqual(job.lease_expires_at, T0 + 30)
        self.assertIsNone(jobs.claim(self.conn, "mail", "w2", now=T0, lease_seconds=30))

    def test_higher_priority_first(self):
        low = jobs.enqueue(self.conn, "mail", {"n": 1}, now=T0)
        high = jobs.enqueue(self.conn, "mail", {"n": 2}, now=T0, priority=5)
        self.assertEqual(jobs.claim(self.conn, "mail", "w1", now=T0, lease_seconds=30).id, high)
        self.assertEqual(jobs.claim(self.conn, "mail", "w1", now=T0, lease_seconds=30).id, low)

    def test_complete_marks_done(self):
        jobs.enqueue(self.conn, "mail", {"n": 1}, now=T0)
        job = jobs.claim(self.conn, "mail", "w1", now=T0, lease_seconds=30)
        jobs.complete(self.conn, job.id, job.lease_token, now=T0 + 1, result={"sent": True})
        self.assertEqual(self.state(job.id), "done")

    def test_failed_job_is_retried_later(self):
        jobs.enqueue(self.conn, "mail", {"n": 1}, now=T0)
        job = jobs.claim(self.conn, "mail", "w1", now=T0, lease_seconds=30)
        self.assertEqual(jobs.fail(self.conn, job.id, job.lease_token, now=T0 + 1, error="smtp timeout"), "ready")
        again = jobs.claim(self.conn, "mail", "w1", now=T0 + 3600, lease_seconds=30)
        self.assertEqual((again.id, again.attempts), (job.id, 2))

    def test_heartbeat_returns_new_expiry(self):
        jobs.enqueue(self.conn, "mail", {"n": 1}, now=T0)
        job = jobs.claim(self.conn, "mail", "w1", now=T0, lease_seconds=30)
        self.assertEqual(jobs.heartbeat(self.conn, job.id, job.lease_token, now=T0 + 10, lease_seconds=30), T0 + 40)

    def test_worker_runs_one_job(self):
        job_id = jobs.enqueue(self.conn, "mail", {"n": 1}, now=T0)
        self.assertEqual(process_one(self.path, "mail", "w1", lambda payload: payload["n"] + 1, now=T0), job_id)
        self.assertEqual(self.state(job_id), "done")
        self.assertIsNone(process_one(self.path, "mail", "w1", lambda payload: None, now=T0))


if __name__ == "__main__":
    unittest.main()
