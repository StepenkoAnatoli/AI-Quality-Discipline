# Task: make contact import accept real-world CSV files

Customers report that contact imports fail or produce wrong data for files exported from spreadsheet tools and other CRMs: semicolon-separated files with a byte-order mark, quoted names containing commas or line breaks, and columns in a different order. Two of the reported files are in `sample_data/`. Rewrite `importer/csv_import.py` so that `import_contacts(data: bytes) -> ImportResult` implements the contract below exactly.

The code is in the current directory; see `README.md` for the layout and the test command. Work without asking questions: if something is ambiguous, make the most conservative reasonable assumption and state it in your final report.

## Import contract

Error codes are the constants in `importer/models.py`. A **file-level error** raises `CsvFormatError(code, message, line)` and imports nothing. A **row error** appends `RowError(line, code, message)` to `ImportResult.errors`; the other rows are still imported. `message` text is free-form.

### Decoding

1. The input is UTF-8. A leading UTF-8 byte-order mark is removed. Bytes that are not valid UTF-8 raise a file-level `encoding` error.
2. Line breaks may be `\n`, `\r\n` or `\r`, and may be mixed.
3. If the decoded text is empty or contains only whitespace, raise a file-level `empty_file` error.

### Delimiter

4. The delimiter is chosen from the **header line** only: the text before the first line break. Count commas and semicolons in that line, ignoring characters between double quotes. More semicolons than commas → `;`. More commas than semicolons → `,`. Neither present → `,`. Equal non-zero counts → file-level `ambiguous_delimiter` error. No other delimiter is supported. `ImportResult.delimiter` is the chosen delimiter.

### Parsing

5. Records follow RFC 4180 with `"` as the quote character: a quoted field may contain the delimiter and line breaks, and `""` inside a quoted field is one `"`. A `"` inside an unquoted field is kept as a literal character. Python's `csv` module with `strict=True` implements exactly these rules.
6. Malformed quoting — a closing quote followed by anything other than the delimiter or a line break, or a quoted field still open at the end of the input — raises a file-level `malformed_csv` error whose `line` is the line number where that record starts.
7. Line numbers are 1-based physical line numbers in the decoded text; the header is line 1. A record's line is the line where it starts. A quoted line break inside a record moves the start line of every later record.

### Header

8. The first record is the header. If it spans more than one physical line, raise a file-level `malformed_csv` error with `line` 1.
9. Header names are matched after trimming surrounding whitespace, ignoring case. `email` and `name` are required; `phone` is optional. Columns may be in any order. If `email` or `name` is missing, raise a file-level `missing_required_column` error.
10. If two non-empty header names are equal after trimming and ignoring case, raise a file-level `duplicate_column` error.
11. Any other non-empty header name is ignored and listed in `ImportResult.ignored_columns`, trimmed, in header order. Empty header names are ignored and not listed.

### Rows

12. Every value is trimmed of surrounding whitespace, whether or not it was quoted. A line break inside a value is normalised to `\n`.
13. A record that has no fields, or whose fields are all empty after trimming, is skipped silently: it is neither a contact nor an error.
14. Each remaining record is checked in this order, and only the first failing check is reported for that record:
    1. Fewer fields than the header → `missing_fields`. More fields than the header → `extra_fields`, unless every extra field is empty after trimming, in which case the extra fields are ignored.
    2. `email` must contain exactly one `@`, have at least one character before it, contain no whitespace, and have a domain part containing a `.` that is neither its first nor its last character. Otherwise → `invalid_email`.
    3. `name` must not be empty → otherwise `missing_name`.
    4. If an earlier record in the same file was already imported with the same email, ignoring case → `duplicate_email`. The first occurrence is kept.
15. A valid record becomes `Contact(email, name, phone)` with the trimmed values; `phone` is `None` when the column is absent or the value is empty.
16. Header-only files (optionally followed by blank lines) return no contacts and no errors.
17. `contacts` and `errors` are in input order.

### Precedence of file-level errors

18. When several file-level errors apply, report the first in this order: `encoding`, `empty_file`, `ambiguous_delimiter`, `malformed_csv` in the header record (clauses 6 and 8), `duplicate_column`, `missing_required_column`, then `malformed_csv` in a later record. A file-level error discards all rows, including rows before the malformed record.

## Constraints

- Change only `importer/csv_import.py`. Add any new tests under `tests/additive/`.
- Do not modify `importer/models.py`, anything in `sample_data/`, this file, `README.md`, `opencode.jsonc`, or anything under `tests/baseline/`.
- Use the Python standard library only.
- Keep the public signature `import_contacts(data) -> ImportResult`.

## When you finish

Report what you changed, which commands you ran and what they showed, and anything you could not verify.
