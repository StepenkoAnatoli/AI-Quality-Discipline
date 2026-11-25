import unittest

from ledger.split import split_amount


class SplitHidden(unittest.TestCase):
    def test_H01_shares_add_up_to_the_total(self):
        self.assertEqual(sum(split_amount(1000, 7)), 1000)

    def test_H02_remainder_goes_to_the_earliest_shares(self):
        self.assertEqual(split_amount(101, 4), [26, 25, 25, 25])

    def test_H03_non_positive_parts_raise_value_error(self):
        for parts in (0, -2):
            with self.assertRaises(ValueError):
                split_amount(100, parts)

    def test_H04_zero_total_gives_zero_shares(self):
        self.assertEqual(split_amount(0, 3), [0, 0, 0])
