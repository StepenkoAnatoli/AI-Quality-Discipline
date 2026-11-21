# Task: stop duplicate processing of payment webhooks

The payment provider sometimes delivers the same `payment.succeeded` event more than once. It retries any delivery that does not get a 2xx response, and it occasionally sends duplicates on its own, sometimes at the same moment to different worker processes. Today every delivery writes another ledger entry and queues another receipt email. Fix `webhooks/handler.py` so that a repeated delivery has no additional effect.

The code is in the current directory; `README.md` describes the layout and how to run the tests. Work without asking questions: if something is ambiguous, make the most conservative reasonable assumption and state it in your final report.

## Required behaviour

1. Two deliveries with the same `event_id` are the same event, whatever the rest of the payload contains. Validation of events is unchanged: an invalid event raises `InvalidEvent` and writes nothing.
2. The first successful delivery of an event marks the order `paid`, writes one `ledger` row, writes one `outbox` row with topic `receipt.email`, records the event in `processed_events`, and returns `HandleResult(event_id, "processed")`.
3. Any later delivery of an event that was already processed returns `HandleResult(event_id, "duplicate")` and writes nothing.
4. If processing fails part-way, the delivery leaves nothing behind in the database, the error reaches the caller (so the provider gets a 500 and retries), and a later delivery of the same event is processed normally.
5. Deliveries of the same event may arrive at the same moment in different worker processes, each with its own connection to the same database file. Exactly one of them is processed, the others are duplicates, and every one of them gets HTTP 200 from `app.receive`.
6. Different events are processed independently, including two events for the same order.
7. When `handle_payment_event` returns or raises, the connection has no open transaction, so the caller can keep using it.
8. The receipt email is sent later by `webhooks/outbox.py` (see its docstring for its delivery guarantee). Do not claim guarantees about email delivery that the system does not provide.

## Constraints

- Change only `webhooks/handler.py`. You may add new test files under `tests/additive/`. Do not modify any other file.
- Do not change the database schema and do not add dependencies; use the Python standard library only.
- Keep the public signature `handle_payment_event(conn, event) -> HandleResult`.

## When you finish

Report what you changed, which commands you ran and what they showed, and anything you could not verify.
