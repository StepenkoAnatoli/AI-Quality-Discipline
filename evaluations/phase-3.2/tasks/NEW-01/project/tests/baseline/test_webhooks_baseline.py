import json
import os
import shutil
import tempfile
import unittest

from webhooks import store
from webhooks.app import receive
from webhooks.handler import handle_payment_event
from webhooks.types import HandleResult, InvalidEvent


def event(event_id="evt_1", order_id="ord_1", amount=2500):
    return {"event_id": event_id, "type": "payment.succeeded", "order_id": order_id, "amount_cents": amount}


class WebhookBaselineTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.db_path = os.path.join(self.tmp, "orders.db")
        conn = store.connect(self.db_path)
        store.init_schema(conn)
        store.add_order(conn, "ord_1", 2500)
        conn.close()
        self.conn = store.connect(self.db_path)

    def tearDown(self):
        self.conn.close()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def count(self, table):
        return self.conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]

    def test_first_delivery_marks_order_paid_and_queues_receipt(self):
        result = handle_payment_event(self.conn, event())
        self.assertEqual(result, HandleResult(event_id="evt_1", status="processed"))
        status = self.conn.execute("SELECT status FROM orders WHERE order_id='ord_1'").fetchone()[0]
        self.assertEqual(status, "paid")
        self.assertEqual(self.count("ledger"), 1)
        self.assertEqual(self.count("outbox"), 1)

    def test_invalid_events_are_rejected_without_writes(self):
        bad = [
            event(order_id="missing"),
            event(amount=1),
            dict(event(), type="payment.failed"),
            dict(event(), event_id=""),
        ]
        for payload in bad:
            with self.subTest(payload=payload):
                with self.assertRaises(InvalidEvent):
                    handle_payment_event(self.conn, payload)
        self.assertEqual(self.count("ledger"), 0)
        self.assertEqual(self.count("outbox"), 0)

    def test_receive_maps_results_to_http_status(self):
        status, body = receive(self.db_path, json.dumps(event()).encode())
        self.assertEqual((status, body["status"]), (200, "processed"))
        self.assertEqual(receive(self.db_path, b"not json")[0], 400)
        self.assertEqual(receive(self.db_path, json.dumps(event(order_id="nope")).encode())[0], 400)


if __name__ == "__main__":
    unittest.main()
