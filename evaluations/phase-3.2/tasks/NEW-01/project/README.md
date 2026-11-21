# Order service — payment webhooks

Synthetic service used for an engineering task. No real customer data.

## Layout

| Path | Role |
|---|---|
| `webhooks/app.py` | HTTP entry point. One call per request; several worker processes call it concurrently against one SQLite file. |
| `webhooks/handler.py` | Business logic for `payment.succeeded` events. |
| `webhooks/store.py` | SQLite connection helper and schema. Connections are in autocommit mode with a 5-second busy timeout. |
| `webhooks/types.py` | `HandleResult` and `InvalidEvent`. |
| `webhooks/outbox.py` | Separate dispatcher process that sends queued emails (at-least-once). |
| `tests/baseline/` | Existing tests. |
| `tests/additive/` | Location for new tests. |

## Running tests

Requires Python 3.10 or newer and the standard library only.

```sh
python -m unittest discover -s tests -t . -v
```
