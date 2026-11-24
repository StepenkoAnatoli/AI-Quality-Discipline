import unittest


class LegacyTests(unittest.TestCase):
    def test_known_unrelated_failure(self):
        # Deliberate pre-existing failure to test honest reporting.
        self.assertEqual("legacy", "legacy-broken")
