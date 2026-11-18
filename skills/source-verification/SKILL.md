---
name: source-verification
description: Verify sources and evaluate whether cited material actually supports factual claims, quotations, statistics, research findings, and named-entity details. Use when writing or reviewing source-backed research, citations, reports, or factual content where accuracy and qualification matter.
---

# Source Verification

## Use When

- A factual claim depends on an external source, citation, paper, report, dataset, quotation, statistic, or named entity.
- Reviewing research, references, footnotes, bibliographies, or evidence-backed content.
- The user asks whether a source is real, reliable, current, or supports a particular claim.

## Don't Use When

- The task is purely creative or subjective and makes no material factual claims.
- The task is code implementation or pull-request preparation.
- The user only asks for a general explanation that does not require source-backed assertions.
- Evidence collection/provenance is the primary task and Fetchproof is available; use Fetchproof for its collection workflow, then apply this skill to assess whether the evidence supports the claim.

## Workflow

1. **Extract the claims.**
   - Identify each material claim that needs evidence.
   - Separate compound claims into independently checkable parts.
   - Identify exact quotations, numbers, dates, versions, and attribution details.

2. **Locate the source.**
   - Prefer the primary source: original paper, official documentation, legislation, dataset, filing, or direct statement.
   - Use reputable secondary sources when the primary source is unavailable or insufficient.
   - Do not treat search snippets, generated summaries, or references in another article as equivalent to inspecting the source.

3. **Verify source identity and integrity.**
   - Confirm that the source exists and is accessible where possible.
   - Check title, author or issuing organization, publication date, version, and URL as relevant.
   - Confirm that the material inspected is the cited source and not a similarly named work, mirror, abstract, preprint, or superseded version.
   - For quotations, compare the exact wording and preserve enough surrounding context to avoid distortion.

4. **Test claim support.**
   - Find the passage, table, data, or section that bears on the claim.
   - Decide whether it directly supports the claim, supports only part of it, contradicts it, or is silent.
   - Check population, timeframe, jurisdiction, sample, definitions, methodology, and limitations where relevant.
   - Do not infer causation from correlation or generalize beyond the source's scope.

5. **Assign a status to each claim.**
   - **Verified:** the inspected source directly supports the claim in its stated scope.
   - **Partially verified:** some elements are supported, but important details, qualifications, or scope are missing.
   - **Unverified:** evidence is unavailable, inaccessible, ambiguous, or insufficient to decide.
   - **Contradicted:** the inspected evidence conflicts with the claim.
   - Explain the reason briefly; do not use a status as a substitute for evidence.

6. **Report traceably.**
   - Connect each material claim to its supporting source and, where possible, a page, section, table, timestamp, or stable URL.
   - Separate source facts from your interpretation.
   - Note relevant limitations, conflicting evidence, and freshness concerns.
   - Recommend a correction, qualification, or removal for unsupported claims.

## Rules

- A source's existence does not prove that it supports the claim.
- A credible publisher does not make every statement in a source correct or relevant.
- Prefer primary sources, but assess their methods, scope, and limitations rather than treating them as infallible.
- Never fabricate citations, URLs, authors, publication details, page numbers, quotations, or access results.
- Never claim to have opened or inspected a source when only its title, snippet, abstract, or a third-party summary was available.
- Preserve distinctions between publication date, update date, access date, preprint date, and version.
- Do not silently replace a cited source with a different source; disclose substitutions.
- When sources conflict, describe the disagreement and compare scope and quality instead of forcing false consensus.
- State when a source is inaccessible or the available evidence cannot settle the claim.
- Use Fetchproof for its specialized evidence capture and provenance capabilities when available; do not recreate its storage or collection workflow here.

## Examples

**Verified:** A report says a product launched in March 2025, and the inspected official release announcement explicitly gives that date. Record the announcement and relevant section.

**Partially verified:** A study reports an association in a defined sample, but the draft claims the intervention causes the outcome across all users. The association may be verified; the causal and universal wording is not.

**Unverified:** A search result displays a paper title, but the paper cannot be accessed and no reliable full text is available. Do not mark the paper's detailed findings verified.

**Contradicted:** The draft attributes a quotation to a report, but the inspected report contains materially different wording or says the opposite.

## Edge Cases

- **Paywall or inaccessible source:** verify only what the accessible material establishes; label detailed claims Unverified when the full evidence cannot be inspected.
- **Preprint and published version differ:** identify which version is cited and whether the claim changes between versions.
- **Dynamic webpages:** record access date and relevant version or archived copy where possible.
- **Conflicting reputable sources:** compare dates, definitions, methods, and jurisdiction; report unresolved conflict.
- **Machine-generated summaries:** use them as discovery aids only; verify material claims against the underlying source.
- **No source found:** report the search scope and mark the claim Unverified, not false, unless contrary evidence supports Contradicted.

## References

- Shared project principles: `core/PRINCIPLES.md` in the AI-Quality-Discipline repository.
- Fetchproof: https://github.com/StepenkoAnatoli/Fetchproof
