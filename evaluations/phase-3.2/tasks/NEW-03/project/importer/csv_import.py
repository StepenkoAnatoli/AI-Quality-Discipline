"""Contact import from uploaded CSV files."""
from .models import (
    EMPTY_FILE,
    INVALID_EMAIL,
    MISSING_REQUIRED_COLUMN,
    Contact,
    CsvFormatError,
    ImportResult,
    RowError,
)


def import_contacts(data):
    """Parse an uploaded CSV file (bytes) into contacts."""
    text = data.decode("utf-8")
    lines = text.splitlines()
    if not lines:
        raise CsvFormatError(EMPTY_FILE, "the file is empty")
    header = [name.strip().lower() for name in lines[0].split(",")]
    if header[:2] != ["email", "name"]:
        raise CsvFormatError(MISSING_REQUIRED_COLUMN, "expected columns: email, name, phone")
    contacts = []
    errors = []
    for number, line in enumerate(lines[1:], start=2):
        if not line.strip():
            continue
        fields = [value.strip() for value in line.split(",")]
        email, name = fields[0], fields[1]
        phone = fields[2] if len(fields) > 2 and fields[2] else None
        if "@" not in email:
            errors.append(RowError(number, INVALID_EMAIL, f"invalid email: {email!r}"))
            continue
        contacts.append(Contact(email=email, name=name, phone=phone))
    return ImportResult(contacts=contacts, errors=errors, delimiter=",")
