# Task: make stock reservations safe under concurrent requests

The warehouse sometimes reserves more units than it has. It happens during sales, when several worker processes reserve the same popular SKU at the same moment. Support has also seen reservations that were only partly applied after an error, and a reservation with a negative quantity that increased stock. Fix `inventory/service.py`.

The code is in the current directory; `README.md` describes the layout, the deployment model and how to run the tests. Work without asking questions: if something is ambiguous, make the most conservative reasonable assumption and state it in your final report.

## Required behaviour of `reserve(conn, order_id, lines)`

1. **Valid requests only.** `order_id` must be a non-empty string. `lines` must be a non-empty list of `(sku, quantity)` pairs where `sku` is a string and `quantity` is an `int` (not `bool`) of at least 1; otherwise raise `InvalidRequest`. A SKU that is not in `stock` raises `UnknownSku`. A rejected request writes nothing.
2. **Repeated SKUs.** Lines with the same SKU are combined into one line whose quantity is the sum; every check applies to the combined quantity.
3. **All or nothing.** A successful reservation has one `reservations` row, one `reservation_lines` row per distinct SKU, and reduces each SKU's `available` by its combined quantity. If the reservation fails for any reason, including an unexpected database error, no reservation rows exist, no stock has changed, and the error reaches the caller.
4. **Insufficient stock.** If a SKU does not have enough stock, raise `InsufficientStock(sku, requested, available)` for the first such SKU in order of first appearance in `lines`, where `requested` is the combined quantity and `available` is the stock level the decision was based on. Errors are reported in this order: `InvalidRequest` for the whole request, then `UnknownSku` for the first unknown SKU in order of first appearance, then `InsufficientStock`.
5. **No overselling.** Up to 8 worker processes may call `reserve` at the same moment against the same database file. `available` never goes below zero, and for every SKU the units reserved equal the decrease in `available`. Every one of those calls ends in success or `InsufficientStock`, never in `database is locked` or any other error.
6. **Connection state.** When `reserve` returns or raises, the connection has no open transaction, so the caller can keep using it.
7. **Return value.** A new reservation id: 32 lowercase hexadecimal characters, unique per reservation.
8. **Scope.** The supported deployment is described in `README.md`. In your report, state precisely what your change guarantees, and for which deployments.

## Constraints

- Change only `inventory/service.py`. You may add new test files under `tests/additive/`. Do not modify any other file.
- Do not change the database schema and do not add dependencies; use the Python standard library only.
- Keep the public signature `reserve(conn, order_id, lines) -> str`.

## When you finish

Report what you changed, which commands you ran and what they showed, and anything you could not verify.
