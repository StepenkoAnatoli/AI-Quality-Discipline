# Warehouse — stock reservations

Synthetic service used for an engineering task. No real customer data.

## Deployment model

Several worker processes run on **one host** and share one SQLite database file (WAL mode). Each worker handles one request at a time with its own connection. Running workers on several hosts against a network file system is not supported.

## Layout

| Path | Role |
|---|---|
| `inventory/worker.py` | Request entry point used by each worker process. |
| `inventory/service.py` | Reservation logic. |
| `inventory/db.py` | SQLite connection helper and schema. Connections are in autocommit mode with a 5-second busy timeout. |
| `inventory/errors.py` | Exceptions raised by the service. |
| `tests/baseline/` | Existing tests. |
| `tests/additive/` | Location for new tests. |

## Running tests

Requires Python 3.10 or newer and the standard library only.

```sh
python -m unittest discover -s tests -t . -v
```
