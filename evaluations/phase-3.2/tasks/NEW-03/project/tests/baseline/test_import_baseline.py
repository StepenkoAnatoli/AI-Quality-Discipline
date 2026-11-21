import unittest

from importer.csv_import import import_contacts
from importer.models import Contact, CsvFormatError


class ImportBaselineTest(unittest.TestCase):
    def test_simple_comma_file(self):
        data = b"email,name,phone\nana@example.com,Ana Diaz,555-0100\nbo@example.org,Bo Li,\n"
        result = import_contacts(data)
        self.assertEqual(
            result.contacts,
            [Contact("ana@example.com", "Ana Diaz", "555-0100"), Contact("bo@example.org", "Bo Li", None)],
        )
        self.assertEqual(result.errors, [])
        self.assertEqual(result.delimiter, ",")

    def test_invalid_email_is_reported_with_its_line(self):
        data = b"email,name,phone\nnot-an-email,Ana,\ncy@example.com,Cy,\n"
        result = import_contacts(data)
        self.assertEqual([c.email for c in result.contacts], ["cy@example.com"])
        self.assertEqual([(e.line, e.code) for e in result.errors], [(2, "invalid_email")])

    def test_header_only_file_imports_nothing(self):
        result = import_contacts(b"email,name,phone\n")
        self.assertEqual((result.contacts, result.errors), ([], []))

    def test_empty_file_is_rejected(self):
        with self.assertRaises(CsvFormatError) as ctx:
            import_contacts(b"")
        self.assertEqual(ctx.exception.code, "empty_file")


if __name__ == "__main__":
    unittest.main()
