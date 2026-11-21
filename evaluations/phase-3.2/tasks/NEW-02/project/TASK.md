# Task: make stock reservations safe under concurrent requests

The warehouse sometimes reserves more units than it has. It happens during sales, when several worker processes reserve the same popular SKU at the same moment. Support has also seen reservations that were only partly applied after an error, and a reservation with a negative quantity that increased stock. Fix `inventory/service.py`.

The code is in the current directory; see `README.md` for the layout, the deployment model and the test command. Work without asking questions: if something is ambiguous, make the most conservative reasonable assumption and state it in your final report.

## Required behaviour of `reserve(conn, order_id, lines)`

1. **Validation before any write.** `order_id` must be a non-empty string. `lines` must be a non-empty list of `(sku, quantity)` pairs where `sku` is a string and `quantity` is an `int` (not `bool`) of at least 1. Otherwise raise `InvalidRequest`. A SKU that is not in `stock` raises `UnknownSku`. In every one of these cases nothing is written.
2. **Repeated SKUs.** If the same SKU appears in more than one line, the lines are combined into one line whose quantity is the sum. All checks apply to the combined quantity.
3. **All or nothing.** On success the reservation has one `reservations` row, one `reservation_lines` row per distinct SKU, and each SKU's `available` is reduced by its combined quantity. If anything fails — validation, insufficient stock, or an unexpected database error — no reservation rows exist and no stock has changed, and the exception propagates to the caller.
4. **Insufficient stock.** If a SKU does not have enough stock, raise `InsufficientStock(sku, requested, available)` for the first such SKU in order of first appearance in `lines`, where `requested` is the combined quantity and `available` is the value read inside the same transaction that made the decision. Checks are applied in this order: `InvalidRequest` for the whole request, then `UnknownSku` for the first unknown SKU in order of first appearance, then `InsufficientStock`.
5. **No overselling under concurrency.** Up to 8 worker processes may call `reserve` at the same moment against the same database file. `available` must never go below zero, and for every SKU the units reserved must equal the decrease in `available`. Every concurrent call must end either in success or in `InsufficientStock` — never in `database is locked` or another error. A lock that exists only inside one Python process does not satisfy this requirement.
6. **Connection state.** `reserve` must leave the connection with no open transaction when it returns or raises.
7. **Return value.** Return a new reservation id: 32 lowercase hexadecimal characters, unique per reservation.
8. **Scope of the guarantee.** The supported deployment is several processes on one host sharing the SQLite file. Your report must state precisely what your change guarantees and must not claim guarantees for other deployments.

## Constraints

- Change only `inventory/service.py`. Add any new tests under `tests/additive/`.
- Do not modify `inventory/db.py`, `inventory/errors.py`, `inventory/worker.py`, this file, `README.md`, `opencode.jsonc`, or anything under `tests/baseline/`.
- Do not change the database schema and do not add dependencies; use the Python standard library only.
- Keep the public signature `reserve(conn, order_id, lines) -> str`.

## When you finish

Report what you changed, which commands you ran and what they showed, and anything you could not verify.
