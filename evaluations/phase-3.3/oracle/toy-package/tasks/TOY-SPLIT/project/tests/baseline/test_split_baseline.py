import unittest

from ledger.split import split_amount


class SplitBaseline(unittest.TestCase):
    def test_even_split(self):
        self.assertEqual(split_amount(90, 3), [30, 30, 30])
