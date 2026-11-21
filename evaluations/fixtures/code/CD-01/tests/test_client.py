import unittest
from client import fetch_user, TimeoutError


class ClientTests(unittest.TestCase):
    def test_returns_request_result(self):
        self.assertEqual(fetch_user("u-1", lambda user_id: {"id": user_id}), {"id": "u-1"})

    def test_propagates_non_timeout_error(self):
        def fail(_):
            raise ValueError("bad request")
        with self.assertRaisesRegex(ValueError, "bad request"):
            fetch_user("u-1", fail)


if __name__ == "__main__":
    unittest.main()
