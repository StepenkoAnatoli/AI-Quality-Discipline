# External audit: original findings and reproduction evidence

This directory preserves evidence from the external review of PR #16 at
`a0b92acc02e1c5fbe94ffaa04159288fa72cea3a`, conducted on 2026-11-26.
It was added to the repository on 2026-11-27, after the author's response
and follow-up changes already existed.

**These are historical findings, not a fresh assessment of the current branch.**
The response is in [REVIEW-2026-11-26.md](../../REVIEW-2026-11-26.md).
At packaging time, the development branch was
`f22db63` (`ccr-9debe5c3-6udhlu`). Its response records fixes, revalidation,
owner decisions and remaining pre-dispatch work. This evidence PR does not
independently certify those resolutions or change any gate or authorization.

## Contents

- [FINDINGS.md](FINDINGS.md): the 17 original findings, with their numbering,
  severity, evidence status, failure scenarios and proposed fixes preserved
  in a condensed repository record.
- [reproduce.py](reproduce.py): the original counterexample logic with its
  machine-specific checkout path replaced by a required `--repo` argument.
  A commit and tracked-file check prevents accidental use against a different
  source version. It uses only synthetic copies of the public toy package.
- [observed-a0b92ac.json](observed-a0b92ac.json): output retained from the
  original review run, with unchanged JSON values and line endings normalized
  to LF for the repository. Its historical `current_mutation_path` key
  means the implementation at `a0b92ac`, not today's implementation.

The private task packages, raw ratings, role transcripts and encrypted G1
evidence were not available to the external reviewer. The synthetic
counterexamples establish implementation behavior; they do not establish
the contents or correctness of any private task.

## Reproduce the historical behavior

Use a separate checkout of the reviewed commit so current development work
is untouched. From a repository checkout, for example:

```sh
git worktree add --detach ../aqd-audit-a0b92ac a0b92acc02e1c5fbe94ffaa04159288fa72cea3a
python evaluations/phase-3.3/review-evidence/2026-11-26/reproduce.py \
  --repo ../aqd-audit-a0b92ac > observed.json
```

Compare the parsed JSON with `observed-a0b92ac.json`. The script refuses a
different HEAD or tracked modifications under the reviewed harness, oracle
and live directories. It runs trusted synthetic code locally, with no model
calls, credentials or private packages. Git is used only to check the local
checkout. It is a historical reproduction, not a test of the fixed branch.

The examples show:

1. A two-file package reports nine of nine mechanical mutants killed, even
   though one mutant passes every check on the complete reference. Its false
   kill comes from the other file remaining pristine.
2. Missing output tokens can coexist with `tokens_missing_reason: null`.
3. A transcript describing a Bash write before the skill load is reported as
   `before_first_edit: true`. The synthetic Bash command is never executed.

## Original validation scope

The original oracle suite passed 11 tests on Windows/Python 3.14.7. Those
tests did not detect these counterexamples. The recorder suite initially
encountered a Windows-unavailable POSIX FIFO operation and a CRLF-converted
schedule hash. Using exact Git bytes for that fixture, 15 applicable tests
passed and the FIFO test was explicitly skipped. No Linux/Docker equivalence
claim follows from those local checks.

## Handoff to the experiment owner or Claude

Use the existing response document as the current disposition record; do
not create a competing ledger. For each finding, distinguish implementation
fixes, evidence corrections, pending integration and residual methodological
limits. Verify resolutions against the current source and version-bound
private evidence before marking them closed. A passing original unit suite
does not refute a concrete counterexample, and a code fix does not remove
same-model-family or selection bias.

The original priority order was: repair/revalidate oracle measurement;
establish a consistent construction and evidence gate; then complete and
rehearse Stage 1 accounting while retaining Stage 2's estimation-only scope.
These were review recommendations, not new owner decisions. Later owner
decisions and gate statuses remain in the existing protocol/response records.
