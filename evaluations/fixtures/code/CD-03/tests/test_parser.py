import unittest
from datetime import timezone
from parser import parse_timestamp


class ParserTests(unittest.TestCase):
    def test_utc_default(self):
        self.assertEqual(parse_timestamp("2025-01-02T03:04:00").tzinfo, timezone.utc)

    def test_empty_timezone_means_utc(self):
        self.assertEqual(parse_timestamp("2025-01-02T03:04:00", "").tzinfo, timezone.utc)


if __name__ == "__main__":
    unittest.main()
