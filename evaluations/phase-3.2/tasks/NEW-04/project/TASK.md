# Task: make the job queue safe for several workers

The job queue in `jobqueue/` was written when the service ran a single worker process. It now runs several worker processes on one host that share one SQLite file, and there have been incidents:
- the same job ran in two workers at once;
- a worker that had stalled finished a job that another worker had already taken over;
- jobs that kept failing were retried forever, with no delay;
- producers that retried an `enqueue` created duplicate jobs.

Rewrite `jobqueue/jobs.py` so that its five functions implement the contract below exactly.

The code is in the current directory; `README.md` describes the layout and how to run the tests. Work without asking questions: if something is ambiguous, make the most conservative reasonable assumption and state it in your final report.

## Contract

Exceptions are the classes in `jobqueue/errors.py`; their message text is free-form. A job's columns are those in `jobqueue/db.py`.

### General

1. **Time.** Every function takes the current time as `now` (seconds) and never reads a clock. All times stored in the database are computed from `now`.
2. **Atomicity.** Each call either takes full effect or writes nothing. If a call raises, the exception reaches the caller and the database is unchanged.
3. **Connections.** `conn` is a connection from `jobqueue.db.connect`. When a function returns or raises, `conn` has no open transaction. If `conn` already has an open transaction when a function is called, raise `InvalidArgument` and leave that transaction as it was.
4. **Concurrency.** Calls may run at the same moment in different worker processes, each with its own connection to the same database file.

### Arguments

5. Arguments are checked before anything is written. A failed check raises `InvalidArgument`. A `bool` is never accepted where a number is expected.
   - `queue`: a `str` of 1 to 32 characters, made of a lowercase ASCII letter followed by lowercase ASCII letters, digits, `_` or `-`.
   - `payload`: a `dict` that satisfies the **JSON rule**: `json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)` succeeds, its result is at most 65,536 bytes in UTF-8, and `json.loads` of that result equals the value. That result is the value's **canonical JSON**.
   - `result`: `None`, or any value that satisfies the JSON rule.
   - `now`: an `int` or `float` that is finite.
   - `delay`: an `int` or `float` that is finite and at least 0.
   - `lease_seconds`: an `int` or `float` that is finite, greater than 0 and at most 3600.
   - `priority`: an `int` from -100 to 100.
   - `max_attempts`: an `int` from 1 to 100.
   - `dedupe_key`: `None` or a `str` of 1 to 200 characters.
   - `worker`: a `str` of 1 to 100 characters.
   - `job_id`: an `int`.
   - `token`: a non-empty `str`.
   - `error`: a `str` of any length.

### `enqueue(conn, queue, payload, *, now, delay=0, priority=0, max_attempts=5, dedupe_key=None) -> int`

6. Creates a job and returns its `id`. The job has state `ready`, `attempts` 0, `available_at = now + delay` and `created_at = now`, and its `payload` column holds the payload's canonical JSON.
7. **Deduplication.** If `dedupe_key` is not `None` and the same `queue` already has a job with that key, in any state, no job is created:
   - If that job's payload is the same JSON value as `payload`, and its `priority` and `max_attempts` equal the arguments, return that job's `id` and write nothing. `delay` is not compared. Payloads are compared as JSON values, not as text.
   - Otherwise raise `DedupeConflict`.

   The same key in a different queue does not match.
8. If several processes call `enqueue` at the same moment with the same `queue` and `dedupe_key` and equal arguments, they all get the same `id`, none of them raises, and exactly one job exists.

### `claim(conn, queue, worker, *, now, lease_seconds) -> Job | None`

9. A job of `queue` is **due** when either:
   - its state is `ready` and `available_at <= now`; or
   - its state is `leased` and its lease has **expired**. A lease has expired when `lease_expires_at <= now`, or when `lease_expires_at` is NULL (see clause 18).
10. First, `claim` moves every job of `queue` that has an expired lease and `attempts >= max_attempts` to state `dead`. It sets `last_error` to `"lease expired"` and clears the lease, meaning `lease_token`, `lease_expires_at` and `leased_by` become NULL. This happens even if no job is claimed afterwards.
11. Then `claim` picks one due job:
    - the highest `priority` first;
    - among equal priorities, the earliest **due time**. That is `available_at` for a `ready` job and `lease_expires_at` for a job with an expired lease. A NULL `lease_expires_at` is earlier than every time.
    - then the lowest `id`.

    If no job is due, `claim` returns `None`.
12. Claiming the job sets state `leased`, adds 1 to `attempts`, sets `leased_by = worker` and `lease_expires_at = now + lease_seconds`, and gives the lease a new `lease_token`. The token is an unpredictable `str` that is different from every token issued before. If the job had an expired lease, `last_error` becomes `"lease expired"`; otherwise `last_error` is unchanged.
13. `claim` returns `Job(id, queue, payload, attempts, lease_token, lease_expires_at)`. `payload` is decoded from JSON, and `attempts` is the value after the increment.
14. While a job's lease has not expired, no `claim` returns that job, even when several `claim` calls run at the same moment in different processes.

### `heartbeat`, `complete` and `fail`

15. These functions need a **valid lease**:
    - `heartbeat(conn, job_id, token, *, now, lease_seconds) -> float`
    - `complete(conn, job_id, token, *, now, result=None) -> None`
    - `fail(conn, job_id, token, *, now, error) -> str`

    The checks happen in this order:
    1. Clause 5 checks the arguments.
    2. If no job has `job_id`, raise `UnknownJob`.
    3. The lease is valid only if the job's state is `leased`, its `lease_token` equals `token`, and `now < lease_expires_at`. Otherwise raise `LeaseLost` and write nothing. A lease that has expired is lost even if no other worker has claimed the job yet.
16. `heartbeat` sets `lease_expires_at = now + lease_seconds` and returns that value.
17. `complete` sets state `done`, stores `result` as its canonical JSON (NULL when `result` is `None`) and clears the lease.

    `fail` stores the first 1,000 characters of `error` in `last_error` and clears the lease. Then:
    - if `attempts < max_attempts`, the job becomes `ready` with `available_at = now + min(10 * 2 ** (attempts - 1), 3600)`, and `fail` returns `"ready"`;
    - otherwise the job becomes `dead` and `fail` returns `"dead"`.

### Jobs written by the previous version

18. The database may contain jobs written by the previous version of this module, which had no leases:
    - Such a job can be in state `leased` with both `lease_token` and `lease_expires_at` NULL, because its worker stopped. It counts as a job with an expired lease (clauses 9 to 11).
    - Its `payload` text may not be canonical JSON, for example `{"b": 1, "a": 2}`. It is still the same JSON value as its canonical form (clause 7).

## Constraints

- Change only `jobqueue/jobs.py`. You may add new test files under `tests/additive/`. Do not modify any other file.
- Do not change the database schema and do not add dependencies; use the Python standard library only.
- Keep the five public function signatures.

## When you finish

Report what you changed, which commands you ran and what they showed, and anything you could not verify.
