---
name: pr-hygiene
description: Prepare, create, review, or update focused pull requests by checking repository contribution rules, inspecting the full change set, and reporting tests, CI, risks, and skipped checks accurately. Use only for pull-request work.
---

# PR Hygiene

## Use When

- Creating or preparing a pull request.
- Reviewing, revising, or updating an existing pull request.
- Preparing a branch and its description for submission to a repository.

## Don't Use When

- Making a local code change without PR preparation or review; use `code-discipline`.
- The user asks for general code explanation or implementation only.
- The task is research or source-backed writing rather than PR work.

## Workflow

1. **Read repository guidance.**
   - Inspect contribution instructions, pull request templates, code ownership rules, required checks, branch conventions, and relevant security policies.
   - Follow the repository's actual process; do not assume every project uses the same workflow.

2. **Understand the PR context.**
   - Identify the base and head branches and the intended purpose of the PR.
   - Inspect the complete branch diff against the correct base, including changed files and relevant commit history.
   - Check for unrelated changes, generated files, secrets, debug artifacts, and accidental scope expansion.

3. **Review the change set.**
   - Compare the full diff with the stated goal.
   - Check that behavior, tests, documentation, and configuration changes are coherent.
   - Identify breaking changes, migration needs, compatibility concerns, security implications, and unresolved decisions.
   - Do not treat a green test suite as proof that the change is correct or complete.

4. **Check validation evidence.**
   - Identify checks required by repository policy and checks relevant to the change.
   - Inspect actual local test results and CI status when access is available.
   - Distinguish checks executed, checks passed, checks failed, and checks not run.
   - Do not claim CI passed when it is pending, inaccessible, skipped, or failed.

5. **Prepare or update the PR.**
   - Write a clear title and description that explain purpose, important changes, and user-visible impact.
   - Include test evidence, skipped checks, risks, and relevant rollout or migration notes.
   - Link issues or related work only when the relationship is known.
   - Do not conceal known limitations to make the PR appear ready.

6. **Final review and handoff.**
   - Re-check the PR diff and description after edits.
   - Confirm the target branch and repository are correct before creating or updating the PR.
   - Report the PR URL or identifier only after the platform confirms it.
   - State review findings and remaining blockers plainly.

## Rules

- Follow repository-specific contribution guidance and templates over generic conventions.
- Inspect the full branch diff, not just the latest commit or a user-provided summary.
- Keep the PR focused; split unrelated work when appropriate, but do not split changes mechanically when they form one coherent unit.
- Never invent test results, CI status, approvals, review comments, linked issues, or mergeability.
- Never dismiss a failing required check as irrelevant without evidence and appropriate authorization.
- Do not merge, release, deploy, or change repository settings unless explicitly requested and authorized.
- Do not impose a universal one-open-PR rule; respect the repository's own policy and the user's workflow.
- Do not rewrite authorship, commit history, or branch contents in a destructive way without clear authorization.
- If the complete diff or CI state is unavailable, disclose the review limitation and avoid claiming a complete review.

## Examples

**Good:** Before opening a PR, read CONTRIBUTING.md and the PR template, compare the entire feature branch with its base, run relevant tests, and include exact test outcomes and skipped integration checks in the description.

**Bad:** Review only the latest commit, write "all tests pass" based on an earlier run, and open the PR without checking the repository template.

**Good:** During review, identify a potential migration risk with file and line references, explain why it matters, and distinguish confirmed defects from questions requiring author clarification.

## Edge Cases

- **No PR template or contribution guide:** follow standard clear PR practices and do not invent repository-specific rules.
- **CI unavailable:** report that CI could not be inspected; do not infer its status from local tests.
- **Large branch diff:** summarize by area, but still inspect all changed files or clearly state which files could not be reviewed.
- **Draft PR:** respect draft status and do not imply it is ready for merge.
- **Unrelated pre-existing changes:** identify them and ask before removing or rewriting user work.
- **Required check failure:** report the failure and its scope; do not bypass branch protections or alter policy to force a merge.

## References

- Shared project principles: `core/PRINCIPLES.md` in the AI-Quality-Discipline repository.
- Quality receipt format: `docs/QUALITY-RECEIPTS.md` in the AI-Quality-Discipline repository.
