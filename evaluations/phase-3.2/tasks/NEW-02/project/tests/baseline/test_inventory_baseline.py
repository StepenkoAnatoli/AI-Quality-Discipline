import os
import re
import shutil
import tempfile
import unittest

from inventory import db
from inventory.errors import InsufficientStock, UnknownSku
from inventory.service import reserve
from inventory.worker import handle_reserve_request


class InventoryBaselineTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.db_path = os.path.join(self.tmp, "stock.db")
        conn = db.connect(self.db_path)
        db.init_schema(conn)
        db.set_stock(conn, "WIDGET", 5)
        db.set_stock(conn, "GADGET", 2)
        conn.close()
        self.conn = db.connect(self.db_path)

    def tearDown(self):
        self.conn.close()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def available(self, sku):
        return self.conn.execute("SELECT available FROM stock WHERE sku = ?", (sku,)).fetchone()[0]

    def test_single_line_reservation_decrements_stock(self):
        reservation_id = reserve(self.conn, "order-1", [("WIDGET", 2)])
        self.assertRegex(reservation_id, re.compile(r"^[0-9a-f]{32}$"))
        self.assertEqual(self.available("WIDGET"), 3)
        lines = self.conn.execute(
            "SELECT sku, quantity FROM reservation_lines WHERE reservation_id = ?", (reservation_id,)
        ).fetchall()
        self.assertEqual(lines, [("WIDGET", 2)])

    def test_multi_line_reservation(self):
        reserve(self.conn, "order-2", [("WIDGET", 1), ("GADGET", 2)])
        self.assertEqual((self.available("WIDGET"), self.available("GADGET")), (4, 0))

    def test_insufficient_and_unknown(self):
        with self.assertRaises(InsufficientStock) as ctx:
            reserve(self.conn, "order-3", [("GADGET", 3)])
        self.assertEqual((ctx.exception.sku, ctx.exception.requested, ctx.exception.available), ("GADGET", 3, 2))
        with self.assertRaises(UnknownSku):
            reserve(self.conn, "order-4", [("NOPE", 1)])
        self.assertEqual(self.available("GADGET"), 2)

    def test_worker_status_codes(self):
        self.assertEqual(handle_reserve_request(self.db_path, {"order_id": "o", "lines": [{"sku": "WIDGET", "quantity": 1}]})[0], 201)
        self.assertEqual(handle_reserve_request(self.db_path, {"order_id": "o", "lines": [{"sku": "GADGET", "quantity": 9}]})[0], 409)
        self.assertEqual(handle_reserve_request(self.db_path, {"order_id": "o"})[0], 400)


if __name__ == "__main__":
    unittest.main()
