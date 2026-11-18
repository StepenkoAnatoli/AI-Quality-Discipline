---
name: writing-specificity
description: Detect vague, generic, padded, repetitive, or unsupported language and improve prose with minimal edits while preserving meaning, voice, and requested tone. Use when drafting, editing, polishing, or reviewing written content; supports detect-only and edit modes.
---

# Writing Specificity

## Use When

- Drafting, editing, polishing, or reviewing prose such as posts, emails, documentation, reports, proposals, and explanations.
- The user asks for writing to sound clearer, more concrete, less generic, more natural, or more persuasive.
- A draft contains claims that may be vague, repetitive, inflated, or unsupported.

## Don't Use When

- The user asks a factual research question rather than for prose review; use `source-verification` when source-backed claims need checking.
- The task is code implementation or PR workflow.
- The user explicitly wants brainstorming, fiction, poetry, humor, or deliberately abstract language; respect the requested form rather than imposing business prose conventions.

## Workflow

1. **Identify the writing goal.**
   - Determine audience, purpose, format, language, and requested tone from the prompt and supplied draft.
   - Preserve the author's intended meaning and distinctive voice.
   - If the user specifies a platform or audience, optimize for that context without inventing facts.

2. **Choose the mode.**
   - **Detect:** identify issues and suggest targeted improvements without rewriting the text.
   - **Edit:** make the smallest changes that materially improve clarity, specificity, flow, or credibility.
   - If the user has not specified a mode, infer it from the request: review/critique means Detect; rewrite/polish means Edit.

3. **Inspect the text.**
   - Find empty openings, generic conclusions, filler, repeated ideas, vague nouns, inflated adjectives, unsupported superlatives, and claims without a clear subject or action.
   - Check whether each paragraph contributes a distinct point.
   - Distinguish intentional emphasis or stylistic repetition from accidental padding.

4. **Improve only what needs improvement.**
   - Replace vague wording with concrete detail already present in the source or supplied context.
   - Prefer active, direct language when it improves readability.
   - Remove repetition without deleting meaningful nuance.
   - Preserve appropriate uncertainty and qualifications.
   - Keep the length aligned with the user's purpose; shorter is not automatically better.

5. **Check fidelity.**
   - Compare the result with the original for changed claims, omitted caveats, altered intent, and tone drift.
   - Do not add metrics, examples, customer outcomes, credentials, quotations, or personal experiences unless supplied or verified.
   - If a useful detail is missing, use a clear placeholder only when the user expects a draft template; otherwise flag the missing detail.

6. **Return the result in the requested format.**
   - In Detect mode, show the issue and why it matters, with a suggested direction where useful.
   - In Edit mode, provide the revised text and briefly note material changes only when helpful.
   - Do not add a long explanation when the user asked for copy-ready writing.

## Rules

- Specificity must come from evidence or user-provided context, not invention.
- Preserve meaning, voice, audience, language, and requested tone unless the user asks to change them.
- Do not force every paragraph to contain a number, named entity, or call to action.
- Do not replace plain language with jargon or elaborate vocabulary merely to sound professional.
- Avoid generic AI-style openings, conclusions, transitions, and claims when they add no information.
- Keep persuasive language credible; do not turn a possibility into a promise or a feature into a proven outcome.
- Do not erase deliberate humor, emotion, rhythm, cultural context, or informal language in the name of polish.
- If the draft's central claim is unsupported, flag it rather than quietly making it sound more certain.

## Examples

**Detect:** "We provide innovative solutions that help businesses reach the next level." Flag "innovative solutions" and "next level" as generic; ask what service is provided and what concrete business outcome is supported. Do not rewrite the sentence in Detect mode.

**Edit:** If the supplied facts say a tool automatically sends appointment reminders and reduces manual follow-up, a focused revision can say that directly. Do not invent a percentage reduction or customer testimonial.

**Preserve voice:** If the user writes a short, humorous social post, improve clarity and remove accidental repetition without turning it into a formal corporate announcement.

## Edge Cases

- **Insufficient context:** do not invent details to fill gaps. Keep the text accurate and identify the one missing fact that would make it more concrete.
- **Conflicting goals:** prioritize explicit user constraints; explain a genuine trade-off between brevity, warmth, detail, and persuasion.
- **Regulated or high-stakes claims:** preserve qualifications and recommend source checking for material factual or compliance claims; do not make legal, medical, or financial claims sound more definitive.
- **Translation or localization:** preserve intent and natural phrasing in the target language rather than translating idioms literally.
- **SEO or platform optimization:** improve discoverability without keyword stuffing, false claims, or sacrificing readability.

## References

- Shared project principles: `core/PRINCIPLES.md` in the AI-Quality-Discipline repository.
- Source verification skill: `skills/source-verification/SKILL.md` in this repository.
