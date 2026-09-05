---
type: Operational Record
title: Response Quality Sample 2026-09-03
description: Early 100-row quality audit of instruction-gated controlled-campaign responses.
tags: [quality, response, danish, truncation, dfm11]
status: draft
last_updated: 2026-09-03
confidence: high
---
# Response Quality Sample 2026-09-03

## Scope

A deterministic sample of 100 newly generated, instruction-audited responses
was drawn on 2026-09-03: 50 medium and 50 long conversations. Queue ordering
means all available production rows were Danish `accessible`; this sample does
not represent English or the general/advanced/specialist strata. It covered 76
topics, all 20 interaction modes, and 333 assistant turns.

Artifacts are under
`logs/koolbardi/dfm11-million-controlled-a4b/quality/response-sample-100-2026-09-03*`.

## Results

- All 100 rows met the stored length-band and exchange-count checks.
- All 333 turns passed deterministic language/structure validation.
- No duplicate assistant turn was found.
- The model judge accepted 58 conversations and 267/333 turns. Every failed
  turn was attributed to an incomplete/cut-off response; no safety or language
  failure occurred.
- Raw token/end-point inspection found definite cap truncation in 81/100
  conversations. The judge missed 39 of these and marked those conversations
  accepted. Only 19/100 were both judge-accepted and free of definite cap
  truncation.
- Content before truncation was generally relevant, detailed, coherent, and
  linguistically strong. Instruction quality was 5/5 for every judged turn;
  the defect is completion control rather than topic or prompt quality.

## Root cause and required correction

The response path calls `pool.chat`, which discards the API `finish_reason`, so
`length_valid` can be true even when an assistant turn ended at `max_tokens`.
The row-level `finish_reason=desired_exchanges` records loop completion, not API
completion. In the sample, 179/333 turns hit the exact generation cap.

Danish assistant text used a median 1.916 Gemma tokens per whitespace word
(1.967 among capped turns). The current prompt permits approximately
`0.60 * token_budget` words, implying median demand around 1.15 times the token
budget. This systematically causes truncation.

Before continuing production responses, capture each turn's API finish reason,
require `stop` rather than `length`, and retry capped turns with a substantially
smaller language-specific word budget. A Danish starting factor around 0.40--
0.42 words/token leaves useful completion margin; retain 0.60 for English only
after separate validation. Final audit should also deterministically reject an
assistant turn with `finish_reason=length`, regardless of judge verdict.

## Corrected regeneration pilots

The response queue was paused at atomic shard boundaries and all 406 pre-fix
response shards plus 59 audits were preserved under directories ending in
`pre-completion-fix-20260903-0220`. No pre-fix response remains eligible for
the final dataset.

The same 100 medium/long instructions were regenerated with language-specific
word targets, four per-turn completion attempts, API finish-reason capture,
and deterministic endpoint checks. Of 100 inputs, 99 produced complete rows;
98/99 passed the model judge and the remaining rejection was a genuine
arithmetic error. All 328 assistant turns and 229 generated follow-up user
turns recorded `finish_reason=stop`; every conversation met its exact band and
4K limit. The one unresolved generation was retained in `response_failures/`,
not emitted incompletely.

A separate extreme-band pilot produced 25/25 complete short rows and 23/25
complete near-limit rows. All 48 emitted rows passed the judge and exact length
checks. Near-limit rows contained 3,159--3,911 rendered tokens (mean 3,749.8),
showing that the correction preserves long conversations rather than solving
truncation by making them uniformly short. The two unresolved near-limit rows
were withheld for later retry/replenishment.

Both JSON-producing judge phases now request strict JSON Schema structured
outputs from vLLM. A live server probe and the test suite verified the schema
path. This removes malformed-JSON parse retries; it does not replace the
completion-aware retries needed for natural-language user and assistant turns.

After production restarted, a deterministic sample of 100 rows from the first
corrected production shards passed both levels of validation: all 100 were
length-valid with exact exchange counts and `finish_reason=stop` for every
generation, and the strict-schema judge accepted all 100 conversations and all
200 assistant turns. The sample, verdicts, and report use the
`response-production-fixed-sample-100-2026-09-03*` artifact prefix in the same
quality directory.

A second live-production check sampled 100 rows from the 16 most recently
completed long-band shards. All were Danish four-exchange conversations. The
strict-schema judge accepted 100/100 conversations and 400/400 assistant
turns; all 700 generated user/assistant turns ended with `finish_reason=stop`.
Rendered lengths were 2,146--3,050 tokens (median 2,831), with 68 topics and
all 20 interaction modes represented. The artifacts use the
`response-live-latest-sample-100-2026-09-03*` prefix.

A later status audit found 18 terminal response shards where only 2.3--4.9%
of rows remained incomplete after bounded retries. The original partial-shard
policy rejected the entire shard above a 2% threshold, contrary to the corpus
rule that every valid row should be retained. Response processing now writes
all complete rows and records every unresolved row separately, regardless of
failure fraction; only a shard with zero successful rows is retried as a
systemic failure.
