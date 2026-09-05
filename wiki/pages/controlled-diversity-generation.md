---
type: Design
title: Controlled Diversity Generation
description: Topic, persona, and interaction-mode conditioning for controlled Koolbardi campaigns.
tags: [generation, diversity, personas, topics, modes]
status: stable
last_updated: 2026-09-04
confidence: high
---
# Controlled Diversity Generation

## Decision

Future initial-request generation should use an explicit, deterministic tuple:

`language + topic + persona + interaction mode + complexity + length band + exchanges`

The topic and interaction-mode marginals must be quota-balanced rather than
left to model sampling. Personas may be sampled without replacement in cycles.
Every selected field and source identifier must remain in row metadata through
generation, audit, and finalization.

This design was implemented on 2026-09-02 for the controlled million-row
restart. The v1 catalog contains 136 topics in 17 domains and 20 interaction
modes. Topic/mode assignment is deterministic and balanced in cycles; persona
selection is a deterministic full-period traversal of each language pool.

Use `nvidia/Nemotron-Personas-USA` for English and
`oliverkinch/danish-personas` for Danish. Consume persona records as generation
conditions, not as training conversations. Prefer occupation, education,
interests, expertise, age band, and broad life context; avoid injecting names,
precise addresses, or unnecessary protected traits into generated requests.

The normalized read-only SQLite store contains all 1,000,000 English records
and all 5,000 Danish records. It omits names, ZIP codes, precise locations,
sex, marital status, and cultural-background fields. English list fields supply
interests and expertise; names are removed from retained Danish interest text.

## Topic ontology

Use at least 128 leaf topics grouped under broad domains. Initial coverage
should include:

- everyday life: household maintenance, cooking, food safety, gardening,
  clothing, consumer choices, budgeting, personal administration, transport,
  travel, relocation, events, hobbies, sports, relationships, parenting, and
  elder care;
- health and wellbeing: exercise, sleep, nutrition, stress, accessibility,
  workplace wellbeing, navigating health services, and interpreting general
  health information, without presenting synthetic personas as real patients;
- education: early learning, primary and secondary school, vocational
  education, university study, teaching, assessment, study strategies,
  information literacy, language learning, and continuing education;
- occupations and professions: agriculture, skilled trades, manufacturing,
  logistics, retail, hospitality, healthcare, social work, education, law,
  public administration, accounting, finance, management, HR, journalism,
  design, engineering, research, and software;
- science and engineering: mathematics, statistics, physics, chemistry,
  biology, medicine, earth science, climate, astronomy, materials, energy,
  electronics, mechanical systems, civil engineering, and laboratory methods;
- computing: programming, debugging, testing, data engineering, databases,
  systems, networking, cybersecurity, AI/ML, web development, automation,
  accessibility, documentation, and technical support;
- society and culture: history, geography, civics, economics, ethics,
  philosophy, psychology, sociology, literature, linguistics, visual arts,
  music, film, media literacy, museums, libraries, and cultural heritage;
- communication and production: email, reports, proposals, plans, lessons,
  presentations, summaries, editing, translation, creative writing, comparison,
  decision support, critique, and structured extraction.

The machine-readable catalog is `catalogs/topic-mode-v1.yaml`.

Maintain stable machine-readable IDs and bilingual labels/descriptions. A
topic should describe subject matter, not imply a stereotyped persona-topic
pairing. Add a low but explicit share for cross-domain combinations.

## Interaction modes

Use 16--24 stable modes, including question answering, explanation, tutoring,
brainstorming, planning, procedural guidance, troubleshooting, calculation,
comparison, recommendation with constraints, judgment against criteria,
argument analysis, development or expansion, critique, revision, summarization,
transformation, classification, extraction, verification, and evaluation of
user-supplied text or data.

Modes involving copied input must receive an actual source passage or a
separately generated payload stored in metadata. The prompt generator must not
claim that text was supplied when it was not. Follow-up turns should preserve
the selected mode initially but may use a controlled transition matrix to add
clarification, challenge, revision, or deeper analysis.

## Sampling and controls

Generate assignments before model calls with seeded balanced allocation.
Balance topic and mode independently at the corpus level, then sample a persona
from a compatible broad stratum. Do not require every Cartesian combination.
Use compatibility rules only for genuine constraints and track rejected
assignments to avoid hidden skew.

The generation prompt should require natural embodiment of the tuple without
naming the topic taxonomy, persona record, or mode. Audit both adherence to the
assigned tuple and conversation quality. Corpus reports should include topic,
mode, occupation/education strata, pairwise coverage, acceptance rate, and
semantic-neighbor concentration by language.

This design addresses semantic mode collapse directly. The controlled restart
keeps the established instruction sampling unchanged at temperature 1.0 and
top-p 1.0; explicit allocation, rather than sampling changes, is the correction.

## Migration

The uncontrolled campaign was held after 210 completed response shards and
preserved as a diagnostic artifact. The replacement uses the separate config
`configs/dfm11-million-controlled-a4b.yaml` and runtime root
`data/koolbardi/dfm11-million-controlled-a4b`. Existing rows are not imported.

`scripts/wait_for_diversity_gate.py` waits for 10,000 rows in each language in
the selected phase (1% of each accepted target), then atomically writes aggregate topic,
domain, mode, persona-reuse, prefix, and TF-IDF near-duplicate measurements plus
a frozen 100-row sample per language.

Instruction generation retries a length-capped row up to three times with
progressively smaller explicit word budgets and different deterministic seeds.
If at most 2% remain bad, the shard preserves every successful row atomically
and records rejected row indices and errors under `instruction_failures/`.
Larger failure bursts still fail the shard as an infrastructure safeguard.

For the production gate, the watcher was explicitly run against `instruction`
rows because initial prompts determine topic diversity. The staged queue
produced 19,968 Danish and 10,240 English prompts before measurement:

| Measure | Danish | English |
|---|---:|---:|
| Topics represented | 136/136 | 136/136 |
| Topic normalized entropy | 0.9999993 | 0.9999963 |
| Modes represented | 20/20 | 20/20 |
| Mode normalized entropy | 0.9999999 | 0.9999997 |
| Unique personas | 5,000 | 10,240 |
| Largest six-word prefix in 100-row sample | 7 | 9 |
| Sample pairs with TF-IDF cosine at least 0.65 | 2 | 0 |
| Sample pairs with TF-IDF cosine at least 0.75 | 0 | 0 |

This passed the automatic gate. `scripts/resume_after_diversity_gate.sh` waits
for the staged response/audit/finalization to finish, atomically releases the
6,073 held instruction shards, and resumes the same campaign and queue. The
report is `logs/koolbardi/dfm11-million-controlled-a4b/diversity-1pct.json`;
the frozen prompts use the adjacent `.sample.jsonl` path.

## Pre-response quality gate

On 2026-09-02, the production campaign added an instruction-audit phase before
full response generation. This supersedes the earlier three-stage sequence for
this config. Deterministic checks cover malformed/empty requests, confident
language mismatch, generation-control leakage, and unusably short requests.
The pinned Gemma teacher then judges the requested topic, interaction mode,
persona coherence, realism, answerability, usefulness, safety, and 4/5 minimum
quality. Minor stylistic flaws alone are explicitly not rejection grounds.

All verdicts and reasons are retained under `instruction_audit/`. Responses are
generated only for accepted rows. Final reports aggregate accepted/rejected
counts by language, topic, domain, mode, persona source, complexity, and length
band. Since the gate can reduce the pre-sized candidate margin, final language
targets must be checked after the first complete pass; any shortfall should be
replenished with the same deterministic diversity allocation rather than by
lowering the acceptance threshold.

The live queue received a SQLite insertion guard that rejects direct
`instruction/` to `response` task insertion. This protected the transition
from the already-running older launcher. That coordinator loaded the updated
phase sequence and entered instruction audit correctly, so the temporary
fallback handoff watcher was retired; existing 59 completed gate-tranche
response/audit shards remain valid.

## Danish response cap

**Superseded on 2026-09-03 by the balanced 500K release target below.** The
selection receipt is retained as historical evidence, and its held shards
remain recoverable.

On 2026-09-03, the live controlled campaign capped Danish response generation
at a projected minimum of 1.1 million complete rows. The original 2.08x Danish
oversampling factor came from a 48.6% pilot acceptance rate dominated by a
subsequently fixed truncation defect; corrected production retains about
98.6% of attempted Danish response rows.

The operation retained every completed and running shard, then atomically held
1,862 surplus pending Danish shards. It selected 1,502 pending shards with a
deterministic SHA-256 order and weighted water-filling across complexity and
length cells. The planning target is 1.11 million complete rows, providing a
roughly 1% buffer over the 1.1 million floor. Existing accessible medium/long
oversupply is unavoidable because accepted rows are not discarded; remaining
capacity is allocated proportionally to underrepresented cells.

The selected sources contain 766,888 instruction-audit-accepted rows across
all 136 topics and 20 modes. Topic and mode normalized entropy are respectively
0.99999955 and 0.99999880. The complete selection receipt, including every
selected shard key and per-cell projections, is
`data/koolbardi/dfm11-million-controlled-a4b/response-selection-da-1100000.json`.
Held shards remain recoverable for targeted replenishment after final audit.

## Balanced 500K release target

The controlled campaign now targets exactly 500,000 final Danish rows and
500,000 final English rows. `final_selection` in
`configs/dfm11-million-controlled-a4b.yaml` requests a 1.05x pre-audit buffer,
so audit selection aims for 525,000 rows per language across the full
complexity-by-length grid.

Response selection is deterministic and extensible. `select-responses` keeps
completed and running work, estimates observed per-cell response retention,
and selects a stable SHA-256-ordered prefix of pending/held shards sufficient
for each buffered cell quota. The current plan projects about 788K physically
generated Danish rows because roughly 365K accessible rows were already
complete before the reduction; only a balanced 525K subset will be audited.
It projects about 530K physically generated English rows. All surplus response
artifacts are retained.

After response generation, `select-audits` selects whole response shards up to
each buffered cell quota and holds the rest before judge workers start.
Finalization then deterministically selects exactly each complexity/length cell
quota and refuses to emit a supposedly complete release if any cell is short.
The active receipts are `response-selection.json` and, after response
completion, `audit-selection.json` in the campaign root.

The live response selection was validated after application. Its selected
pending source rows cover every topic, mode, and topic/mode pair in both
languages. Topic and mode normalized entropy exceed 0.999997 in each language;
pair entropy is 0.999882 for Danish and 0.999908 for English. Thus the work
reduction does not reintroduce the earlier semantic mode collapse.

To extend the corpus later, raise `final_selection.targets` and rerun
`select-responses`; the stable ordering releases a superset of prior shards.
After those responses complete, run `advance-queue` and `select-audits` again.
Previously completed rows and audits remain valid, and stable row IDs prevent
duplication.

## English pool validation

The complete English instruction-audited pool was measured on 2026-09-03. It
contains 1,047,752 accepted rows out of 1,049,978 generated rows (99.788%). All
136 topics occur 7,578--7,721 times and all 20 modes occur 52,214--52,475
times. Every one of the 2,720 topic/mode pairs is represented 351--387 times;
normalized entropy is 0.99999897 for topics, 0.99999959 for modes, and
0.99999805 for pairs.

Complexity shares match the configured 20/50/20/10 allocation and length-band
shares match 20/35/35/10 after auditing. The pool uses 998,007 distinct
sanitized English personas; each occurs once or twice. The small completed
English response prefix is currently all accessible/short because response
task IDs are consumed in order, but no English shards were held by the Danish
cap, so this transient prefix is not the final distribution.

## Final controlled campaign result

The campaign completed on 2026-09-04. Finalization used the stable balanced
selection as a minimum rather than a hard cap: `retain_surplus: true` preserved
every otherwise qualifying audited row. A targeted English general/near-limit
replenishment and a 1.07 audit-selection buffer resolved the final cell
shortfall without weakening any audit criterion.

The immutable `final.jsonl` contains 535,930 Danish rows and 528,926 English
rows. Their exact native Gemma-4 rendered-token totals are respectively
1,165,181,804 and 1,147,687,693. Every required complexity-by-length cell meets
its target. The adjacent finalizer report records 13,730 rejected rows, and the
queue ended with 2,198 completed and 511 intentionally held tasks, with no
pending, running, or failed work.

The source SHA-256 is
`07f461b7c9adc2c49cb7a8c77bb29060200218568e2684229bcc79128bdc15e1`.
Compact publication packages were uploaded as
`schneiderkamplab/dfm11-koolbardi-da` and
`schneiderkamplab/dfm11-koolbardi-en`.
