# Task: stop duplicate processing of payment webhooks

The payment provider sometimes delivers the same `payment.succeeded` event more than once: it retries when it does not receive a 2xx response, and it occasionally sends duplicates on its own, sometimes at the same moment to different worker processes. Today every delivery writes another ledger entry and queues another receipt email. Fix `webhooks/handler.py` so that duplicate deliveries have no additional effect.

The code is in the current directory; see `README.md` for the layout and the test command. Work without asking questions: if something is ambiguous, make the most conservative reasonable assumption and state it in your final report.

## Required behaviour

1. **Idempotency key.** The key is `event_id`. Two deliveries with the same `event_id` are the same event, whatever the rest of the payload contains. Existing validation is unchanged: an invalid event raises `InvalidEvent` before anything is written.
2. **First delivery.** The first successful processing of an `event_id` sets the order status to `paid`, writes exactly one `ledger` row, writes exactly one `outbox` row with topic `receipt.email`, records the `event_id` in `processed_events`, and returns `HandleResult(event_id, "processed")`.
3. **Redelivery.** A delivery of an `event_id` that has already been processed returns `HandleResult(event_id, "duplicate")` and writes nothing.
4. **Atomicity.** The order update, ledger row, outbox row and `processed_events` row are committed together or not at all. If any step fails, nothing from that delivery remains in the database, the exception propagates to the caller (so `app.receive` answers 500 and the provider retries), and a later delivery of the same event is processed normally.
5. **Concurrency.** Several worker processes, each with its own connection, may deliver the same event at the same moment against the same database file. Exactly one delivery is processed; every other one is reported as a duplicate. Every such delivery must get HTTP 200 from `app.receive`, never 500. A lock that exists only inside one Python process does not satisfy this requirement.
6. **Independent events.** Different `event_id`s are processed independently, including two events for the same order.
7. **Connection state.** `handle_payment_event` must leave the connection with no open transaction when it returns or raises, so the caller can keep using it.
8. **Email delivery.** The receipt email itself is sent later by `webhooks/outbox.py`, which delivers at-least-once and relies on the email service deduplicating by `dedupe_key` (the `event_id`). Your change must guarantee one outbox row per event; it cannot make the email itself exactly-once, and your report must not claim that it does.

## Constraints

- Change only `webhooks/handler.py`. Add any new tests under `tests/additive/`.
- Do not modify `webhooks/app.py`, `webhooks/store.py`, `webhooks/types.py`, `webhooks/outbox.py`, this file, `README.md`, `opencode.jsonc`, or anything under `tests/baseline/`.
- Do not change the database schema and do not add dependencies; use the Python standard library only.
- Keep the public signature `handle_payment_event(conn, event) -> HandleResult`.

## When you finish

Report what you changed, which commands you ran and what they showed, and anything you could not verify.
