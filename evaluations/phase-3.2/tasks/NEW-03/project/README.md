# CRM — contact import

Synthetic service used for an engineering task. No real customer data.

## Layout

| Path | Role |
|---|---|
| `importer/csv_import.py` | `import_contacts(data: bytes) -> ImportResult`. |
| `importer/models.py` | `Contact`, `RowError`, `ImportResult`, `CsvFormatError` and the error-code constants. |
| `sample_data/` | Two files customers reported as failing. |
| `tests/baseline/` | Existing tests. |
| `tests/additive/` | Location for new tests. |

## Running tests

Requires Python 3.10 or newer and the standard library only.

```sh
python -m unittest discover -s tests -t . -v
```
