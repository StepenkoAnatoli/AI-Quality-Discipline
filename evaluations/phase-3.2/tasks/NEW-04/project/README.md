# Jobs — background job queue

Synthetic service used for an engineering task. No real customer data.

## Deployment model

Producers add jobs; worker processes claim them, run them and report the outcome. Several worker processes run on **one host** and share one SQLite database file (WAL mode). Each worker uses its own connection. Running workers on several hosts against a network file system is not supported.

## Layout

| Path | Role |
|---|---|
| `jobqueue/jobs.py` | Queue operations: `enqueue`, `claim`, `heartbeat`, `complete`, `fail`. |
| `jobqueue/worker.py` | Entry point used by each worker process. |
| `jobqueue/db.py` | SQLite connection helper and schema. Connections are in autocommit mode with a 5-second busy timeout. |
| `jobqueue/models.py` | `Job`, the value returned by `claim`. |
| `jobqueue/errors.py` | Exceptions raised by the queue. |
| `tests/baseline/` | Existing tests. |
| `tests/additive/` | Location for new tests. |

## Running tests

Requires Python 3.10 or newer and the standard library only.

```sh
python -m unittest discover -s tests -t . -v
```
