# Quality receipts

A quality receipt is a compact, auditable record of what an agent was asked to do, what it actually delivered, and what evidence supports its claims.

It is intended for substantial work: code changes, research, writing that carries factual claims, and pull requests. Do not emit one for every trivial conversational reply or routine edit. Keep the receipt internal or attach it to a deliverable, task record, or PR when useful; do not force it into the user-facing response unless requested or materially helpful.

## Template

```text
Requested:
Delivered:
Scope deviations:
Checks executed:
Checks passed:
Checks skipped:
Evidence:
Remaining uncertainty:
```

## Field rules

- **Requested:** State the user's actual requested outcome, not an expanded interpretation.
- **Delivered:** Describe what exists now. Separate completed work from recommendations, drafts, or proposed work.
- **Scope deviations:** Record additions, omissions, substitutions, or changed assumptions. Write "None" only after comparing the result with the request.
- **Checks executed:** List checks that were actually run, with enough detail to identify the command, procedure, source review, or reviewer.
- **Checks passed:** List only checks whose results were observed and passed. A check being run does not mean it passed. If none passed, say so.
- **Checks skipped:** List relevant checks that were not run and why. Do not hide skipped checks or imply they passed.
- **Evidence:** Point to inspectable support: command output, test logs, file paths and line ranges, commit/PR links, source URLs, captured passages, or other artifacts. Evidence must support the specific claim being made.
- **Remaining uncertainty:** State unresolved questions, untested cases, limitations, assumptions, and risks. Use "None known" only when that is an honest, bounded statement—not as a guarantee.

## Integrity rules

1. Never invent a check, result, source, log, or artifact.
2. Never move an item from "executed" to "passed" without observing its result.
3. A proposed command is not an executed check. A generated test is not a passing test.
4. Keep evidence proportional: link or identify the artifact; do not paste entire logs when a stable reference will do.
5. Preserve uncertainty. A passing check supports only the scenarios it covers; it does not prove universal correctness.
6. If work is partial, say so in **Delivered** and identify the remaining work under **Remaining uncertainty** or **Checks skipped**.
7. Keep the receipt concise and task-specific. Omit empty boilerplate; use "None" only where the field is meaningful and has been checked.

## Example

```text
Requested:
Fix the CSV export failing when a field contains a comma.

Delivered:
Updated CSV serialization to quote fields containing commas and escaped quotes.

Scope deviations:
None.

Checks executed:
- Ran the focused CSV export test module.
- Ran the full unit test suite.
- Inspected the final diff.

Checks passed:
- Focused CSV export tests.
- Full unit test suite.

Checks skipped:
- End-to-end export against the production storage service; no production access was authorized.

Evidence:
- `tests/test_csv_export.py` — regression case for commas and embedded quotes.
- CI run: <link>
- Commit: <sha-or-link>

Remaining uncertainty:
Production storage integration was not exercised.
```

## Relationship to the quality skills

A receipt is a reporting format, not a substitute for verification.

- **code-discipline:** records the request-to-diff comparison and checks actually run.
- **pr-hygiene:** supplies concise, evidence-backed PR test and risk disclosures.
- **source-verification:** points to sources and captured passages supporting material claims.
- **writing-specificity:** records material scope changes and unresolved factual claims.
- **Break Test / Fetchproof / Holdshort:** may provide evidence or outcomes, but their gates do not make every receipt field true automatically.

The agent remains responsible for checking that each statement in the receipt matches the actual task state.
