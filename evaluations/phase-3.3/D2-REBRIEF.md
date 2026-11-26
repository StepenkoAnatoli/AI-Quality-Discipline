# Re-brief of the remaining 18 tasks, with the medium tier first (proposal, 2026-11-26)

**Status:**
- **Ratified by the owner on 2026-11-26** ("ratify the D2 rebrief proposals"): every item in §6. Nothing is built by this document itself.
- **It answers two things:**
  - the main G2 finding, that the medium tier is under-filled (`G2-BUILD.md` §5 item 1);
  - review finding 11, that difficulty is confounded with task content.
- **When it applies:** only if the owner passes G2 after spot check 1.

**This is a public document.** It holds briefs and rules only. Per-factor ratings stay in the private repository.

## 1. What the pilot batch showed

**Ratings at or above the middle anchor.** Both tasks briefed as medium (M3, M6) were rated at or above the middle anchor (2) on most of the seven intrinsic factors. Seven factors at 2 already sum to 14, which is hard (≥ 13). A brief written as "a bit of everything" lands in hard.

**What pushed them up:** two modules changed, state across runs, partial failure, and compatibility with stored data. Each was reasonable alone; together they exceed 12.

**The consensus rule is not fully specified.** `REVIEW-2026-11-26.md` §3 says the consensus per factor is "the rounded mean" of the two raters, but does not say how a half is rounded. With two raters one point apart on a factor, the mean is always a half.

| Task | Composites, Opus / Sonnet | Consensus under half-up / half-down / half-to-even | Tier |
|---|---|---|---|
| E4 | 4 / 6 | 6 / 4 / 4 | easy in every case |
| M3 | 13 / 15 | 15 / 13 / 14 | hard in every case |
| **M6** | **12 / 13** | **14 / 11 / 13** | **depends on the convention** |
| H4 | 13 / 15 | 15 / 13 / 13 | hard in every case |
| E6, H6 | equal | equal | easy, hard |

**Amendment to §3 rule 1 (ratified 2026-11-26):**
- **The consensus composite** is the sum of the per-factor means, without rounding them.
- **The tier** follows from that sum by the rubric's cut points.
- **A sum that falls strictly between two tiers** (6.5, or 12.5) is a boundary case. A third, fresh rater session rates the task, and the tier follows from the median of the three composites.
- **A factor where two raters differ by more than one point** still gets a third rating, as before.

**Disclosure:** this amendment is proposed by the orchestrating session after it has seen the pilot ratings. It does not pick M6's tier: under it, M6 (12.5) goes to a third rater.

**Effect on the batch:**
- **Easy:** E4 and E6.
- **Medium:** none for certain; M6 is undecided.
- **Hard:** M3 and H4, H6, plus M6 if it rates hard.

The task IDs stay as they are: an ID is a label, and the rated tier is what counts (`DESIGN.md` §3).

## 2. Volume needed

**Target:** D2 is 8 tasks per tier (24 in all), so 18 remain to be built.

| Tier | Rated so far | Still to build | From the existing briefs (`DESIGN.md` §4) | New briefs (§4 below) |
|---|---|---|---|---|
| Easy | 2 | 6 | E1, E2, E3, E5 | E7, E8 |
| Medium | 0 or 1 (M6) | 7 or 8 | M1, M2, M4, M5, each re-scoped (§3) | M7, M8, M9, and M10 if M6 rates hard |
| Hard | 3 or 4 | 4 or 5 | H1, H2, H3, H5 | H7 if M6 rates medium |

**The total is 18 either way.** M10 or H7 is built depending on M6's third rating.

**Overshoot rule (ratified 2026-11-26):**
- **A task that rates into a different tier** keeps that tier. It is never re-labelled to fill a quota, and never discarded.
- **Continuing:** building continues until every tier has at least 8 rated tasks, up to 4 tasks beyond the 24.
- **Logging:** every built task, and its rating, is logged.
- **A tier with more than 8 tasks:** the sealed draw takes 2 of them for calibration; the rest are confirmatory.

## 3. A factor budget for medium briefs

**Goal:** a planned intrinsic composite of **9 to 10**, the middle of the medium range (7–12), so that one rater point either way stays medium.

**The budget** is a design constraint given to the builder. The raters never see it.

| Factor | Medium budget |
|---|---|
| F1 interacting requirements | 2: one ordering or precedence rule |
| F2 state space | at most 1 |
| F3 cross-module | 1 or 2: either one module with a load-bearing caller, or two modules |
| F4 concurrency / failure | at most 1: errors propagate; **no concurrency, no crash recovery, no expiry** |
| F5 compatibility | 1 or 2 |
| F7 verification demand | at most 1: unit tests are enough |
| F8 existing coverage | 1 or 2 |

**Rules for the build:**
- **At most one** of F2, F4 and F7 may go above its budget, and then by one point.
- **Neither of the pilot's two causes of overshoot may appear in a medium task:**
  - state persisted across runs, together with resumption;
  - stored-data compatibility, together with partial failure.

**Re-scoping the four existing medium briefs:**

| ID | Brief (`DESIGN.md` §4) | Re-scoped to | What it drops |
|---|---|---|---|
| M1 | HTTP client retries: idempotency-aware, backoff, server hints | The retry decision only: which requests are retried, and how the server's `Retry-After` hint caps the delay. Client plus one caller; the delay comes from an injected clock | Real timing and jitter verification (F7) |
| M2 | Invoice rounding: line vs total, compatible with stored invoices | Unchanged in scope. Stored invoices are read only; nothing is migrated | Already within budget if no migration is added |
| M4 | Read-through cache: TTL, negative caching, invalidation from two writers | A cache with negative caching and invalidation from **two write paths in one process**. Time is an injected clock; no concurrent writers | Concurrency and expiry under contention (F4) |
| M5 | Config v1 → v2 reader that keeps v1 files working | Unchanged in scope. The reader is read-only: no writing back, no in-place upgrade | Upgrade-in-place state (F2) |

## 4. New briefs, matched across tiers (finding 11)

**The confound:** in the pilot, easy tasks were configuration and CLI work, while hard tasks were concurrency and persistence. So "difficulty" and "kind of task" moved together.

**The response:** group tasks into **families**, each with one task per tier where possible. The tier contrast can then be read within a family. The new briefs fill the gaps in the families.

| Family | Easy | Medium | Hard |
|---|---|---|---|
| Rate limits and retries | E2 `Retry-After` parsing | M1 retry decision | H6 cross-process rate limiter |
| Schema and migration | **E7** (new) | M3 (rated hard) | H5 online schema change |
| Configuration | E4 environment override | M5 v1 → v2 reader | **H7** (new, if needed) |
| Time and calendars | E3 timezone-aware formatting | **M7** (new) | H4 scheduler across DST |
| Import, storage and paging | E1 pagination cursor | M6 (boundary) | H3 crash-safe key-value file |
| Money and orders | **E8** (new) | M2 invoice rounding | H1 order placement with compensation |
| Caching and accounts | E5 stable slugs | M4 cache invalidation | H2 event-sourced projection |
| Command-line and parsing | E6 `--dry-run` | **M8** (new) | |
| Reporting and exports | | **M9** (new); **M10** (new, if needed) | |

| ID | Target | Problem | Changes |
|---|---|---|---|
| E7 | easy | Migration runner: a `status` command that lists applied and pending migrations in order | one module |
| E8 | easy | Currency formatting of negative amounts and zero-decimal currencies | one function |
| M7 | medium | Due dates in business days from a holiday file; due dates already stored stay unchanged | calendar + caller |
| M8 | medium | Query parser: quoted phrases and negation added to an existing tokenizer; old queries keep their results | parser + search |
| M9 | medium | CSV export with column selection and a header order an existing importer accepts | exporter + importer |
| M10 | medium (if M6 rates hard) | Account statement: running balance with reversed transactions, matching stored statements | statement + ledger |
| H7 | hard (if M6 rates medium) | Live configuration reload across worker processes: validate, then switch over atomically | loader + workers |

**What the briefs state:** problems and modules only. The defect classes, hidden checks and reference solutions are written in the private packages, as before (`DESIGN.md` §4).

## 5. Process changes for the remaining build

1. **Blind labels for the raters.** Raters have seen IDs such as "M3", which announce the target tier and can anchor a rating.
   - From now on, every rating branch names the task by a random label.
   - The mapping is kept in the private `build-log/`.
2. **Building order:**
   - **First wave:** the medium tasks, because they are the uncertain tier.
   - **After the first wave:** rate it, and adjust the budget if needed. The adjustment applies only to tasks not yet built, and is logged.
3. **Everything else unchanged:**
   - the solo protocol (`STAGE0-SOLO.md` §2), including the fixed revision routing (§2.6) and the compatibility-wording policy;
   - the validator;
   - the container check;
   - the hash manifest;
   - spot check 2, before the freeze.

## 6. For the owner to decide

1. **Rounding:** the consensus amendment in §1, and the third rating for M6.
2. **Volume:** the volume, the overshoot rule and the cap of 4 extra tasks (§2).
3. **Medium design:** the medium factor budget and the four re-scoped briefs (§3).
4. **New briefs:** E7, E8, M7 to M10 and H7 (§4).
5. **Process:** blind rater labels, and building the medium tier first (§5).
