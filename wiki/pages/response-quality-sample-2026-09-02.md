---
type: Evaluation
title: Response Quality Sample 2026-09-02
description: Manual inspection of ten English and ten Danish response-stage conversations from the million-row campaign.
tags: [quality, sampling, danish, english, responses]
status: stable
last_updated: 2026-09-02
confidence: high
---
# Response Quality Sample 2026-09-02

## Method

Twenty response-stage rows were selected deterministically by sorting
`sha256("quality-sample-v1:" + row_id)` within each language and retaining the
first ten available at selection time. The row IDs below freeze the sample even
as active generation adds files. Inspection covered relevance, coherence,
language, usefulness, topic diversity, and whether every generated turn ended
as complete text. These rows had not necessarily passed model audit.

## Results

| Language | Cleanly complete conversations | Incomplete conversations | Topic distribution |
|---|---:|---:|---|
| English | 9/10 | 1/10 | Eight travel, two gardening |
| Danish | 4/10 | 6/10 | Ten travel; six Copenhagen |

The substantive content was generally relevant, coherent, natural, and useful
until any cutoff. Responses favored repetitive headings, bold lists, itinerary
templates, and phrases such as "Pro tip" or "Rigtig god tur". Travel facts were
often stated confidently and were not independently verified in this sample;
one response contained the apparent typo "Kanshan Airport". The severe topic
concentration indicates initial-request mode collapse that per-row quality
auditing alone will not detect.

| Row | Frozen ID prefix | Assessment |
|---|---|---|
| EN1 | `af6f6be4` | Relevant Kyoto advice, but second user turn ends at "feel particularly" |
| EN2 | `1abf7b7d` | Complete, coherent Japan itinerary conversation |
| EN3 | `2fd65e18` | Complete, useful balcony-herb conversation |
| EN4 | `f262d674` | Complete but highly templated Japan itinerary |
| EN5 | `e88deaa9` | Complete Olympic Peninsula travel advice |
| EN6 | `be480153` | Complete Dolomites hiking advice |
| EN7 | `b2ac3561` | Complete beginner gardening advice |
| EN8 | `64121377` | Complete North Cascades hiking advice |
| EN9 | `5871a4bd` | Complete but repetitive Japan itinerary |
| EN10 | `8121014c` | Complete northern-Japan itinerary |
| DA1 | `5efaea76` | Final user and assistant turns cut off mid-sentence |
| DA2 | `028cce87` | Complete Copenhagen weekend conversation |
| DA3 | `5ac1fcb9` | Three assistant turns cut off mid-word or mid-sentence |
| DA4 | `c5e21699` | Two assistant turns cut off mid-word or mid-sentence |
| DA5 | `e05501c2` | Initial typo and final assistant turn cut off |
| DA6 | `6aed44cf` | Final assistant turn cut off |
| DA7 | `0038996a` | Complete and coherent Garda family-trip advice |
| DA8 | `98b8a674` | Two assistant turns cut off mid-word or mid-sentence |
| DA9 | `025ca5d3` | Complete Copenhagen family-day conversation |
| DA10 | `b2be7fe7` | Complete Copenhagen family-trip conversation |

## Pipeline implications

All sampled rows reported `length_valid=true` and completed the requested
exchange count. Therefore, that flag establishes token/exchange compliance but
does not establish semantic completion. The OpenAI client currently returns
only response text and discards `choices[0].finish_reason`; the pipeline cannot
directly distinguish a length-capped turn from a naturally completed one.

The later model audit should reject many cutoffs through its response-quality
and coherence gates. The Danish pilot's 48.5771% usable rate, versus 99.0706%
for English, is consistent with the observed asymmetry. However, relying only
on audit wastes response and judge compute and depends on the judge noticing
every cutoff.

Before a future campaign, retain finish reasons, mark length-capped turns, and
retry them with a smaller semantic/word budget. Add deterministic incomplete
ending checks as a conservative signal, not a sole rejection rule. Separately,
add corpus-level topic-diversity measurement or topic conditioning because
turn-wise quality judges cannot prevent large-scale itinerary mode collapse.

## Sampling-parameter assessment

The initial-request sampler already uses temperature 1.0 and top-p 1.0. Raising
temperature to approximately 1.1--1.2 may increase wording and occasional topic
variation, but it is not an adequate correction for semantic mode collapse and
may increase malformed or low-quality requests. Presence/frequency penalties
operate within one generated request and cannot enforce diversity across
independent rows. Response temperature should remain conservative; raising it
does not change topics already fixed by the initial-request phase and may worsen
factuality and completion.

The durable correction is explicit corpus-level control: sample balanced topic
and request-archetype labels, vary initial meta-prompt families, optionally seed
requests from a broad source corpus, track realized topic frequencies, and apply
semantic near-duplicate filtering. The topic and archetype must be retained as
row metadata so balance can be measured after audit. Exact normalized-prompt
deduplication alone is insufficient.

The active vLLM 0.27.1 installation defaults to `top_k=0` and `min_p=0`, both
disabled. Koolbardi does not currently send either field. Thus temperature 1.0
and top-p 1.0 use the model's original probability distribution without a
top-k or nucleus cutoff; this is not uniform random sampling. Top-p 1.0 was
chosen to avoid narrowing diversity during initial synthesis. A future
quality/diversity experiment may compare temperature 1.1 with top-p 0.95: the
higher temperature broadens likely choices while the nucleus cutoff removes
the most pathological tail. It still requires explicit topic allocation.

## 100-row topic-diversity follow-up

A second deterministic sample selected 100 initial user requests per language
using a separate hash seed. At selection time the English population contained
8,500 rows and the growing Danish population contained 74,030 rows. A simple
domain classifier found the following distribution:

| Domain | English | Danish |
|---|---:|---:|
| Travel | 57 | 96 |
| Gardening | 20 | 0 |
| Home/ergonomics | 4 | 0 |
| Technology | 3 | 0 |
| Business/career | 2 | 0 |
| Creative/writing | 2 | 0 |
| Cooking | 1 | 0 |
| Health/fitness | 1 | 0 |
| Science/engineering | 0 | 1 |
| Other | 10 | 3 |

Within English travel, 29 requests concerned Japan and 11 the Dolomites.
Within Danish travel, 45 concerned Copenhagen and 27 Italy. Eighty-two of 100
Danish requests began with the normalized six-word prefix `hej jeg sidder og
planlaegger en`; the most frequent English prefix occurred 12 times.

Character 3--5-gram TF-IDF cosine similarity found no English pair above 0.65
and one Danish pair above 0.65; neither language had a pair above 0.75. This is
not evidence of useful diversity: requests vary enough lexically to evade a
strict near-duplicate threshold while repeating the same semantic templates.
The result confirms semantic topic/archetype collapse and reinforces the need
for explicit balanced labels and embedding-based or classifier-based corpus
auditing in future campaigns.
