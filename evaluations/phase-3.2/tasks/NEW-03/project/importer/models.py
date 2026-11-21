from dataclasses import dataclass, field
from typing import List, Optional

# File-level error codes (CsvFormatError.code)
ENCODING = "encoding"
EMPTY_FILE = "empty_file"
AMBIGUOUS_DELIMITER = "ambiguous_delimiter"
MISSING_REQUIRED_COLUMN = "missing_required_column"
DUPLICATE_COLUMN = "duplicate_column"
MALFORMED_CSV = "malformed_csv"

# Row-level error codes (RowError.code)
MISSING_FIELDS = "missing_fields"
EXTRA_FIELDS = "extra_fields"
INVALID_EMAIL = "invalid_email"
MISSING_NAME = "missing_name"
DUPLICATE_EMAIL = "duplicate_email"


@dataclass(frozen=True)
class Contact:
    email: str
    name: str
    phone: Optional[str]


@dataclass(frozen=True)
class RowError:
    line: int
    code: str
    message: str


@dataclass
class ImportResult:
    contacts: List[Contact]
    errors: List[RowError]
    delimiter: str
    ignored_columns: List[str] = field(default_factory=list)


class CsvFormatError(ValueError):
    """The file as a whole cannot be imported."""

    def __init__(self, code, message, line=None):
        super().__init__(message)
        self.code = code
        self.line = line
