---
type: Technical Reference
title: Data Contract
description: Exact format, length, audit, and retention guarantees for generated conversations.
tags: [data, gemma, chat-template, audit]
status: stable
last_updated: 2026-09-02
confidence: high
---
# Data Contract

## Native chat format

The configured tokenizer is authoritative. Boundaries, prompt token IDs,
tokenizer hashes, and template hashes are derived rather than hard-coded.
Final examples contain ordinary `messages` dictionaries with `user` and
`assistant` roles and are intended to be rendered with that tokenizer's native
chat template.

Generation-only meta-prompts, temporary assistant completeness controls, and
judge prompts must never appear in final `messages`. Their relevant hashes and
generation metadata remain in row provenance.

## Exact 4K safety

- `max_sequence_tokens` is 4,096 for the DFM11 campaigns.
- `soft_sequence_tokens` is 3,968, reserving native-template overhead.
- Complete conversations are rejected rather than truncated.
- Exact counts use `apply_chat_template(..., tokenize=True,
  return_dict=False)` and count token IDs.
- The pipeline reserves at least 64 tokens for a future user request and 192
  tokens for its answer in the million campaign.
- Each row records desired and actual exchanges, rendered token count, finish
  reason, and per-turn token budgets.
- Each generated turn records its API finish reason, actual output tokens, and
  completion-attempt count. `finish_reason=length`, an unclosed code fence, an
  incomplete function-word ending, or no plausible terminal boundary cannot
  enter an accepted conversation. Capped turns are regenerated rather than
  truncated.

The explicit `return_dict=False` is critical. A previous implementation took
`len(BatchEncoding)`, which returned the number of mapping fields (`2`) rather
than the number of tokens.

## Length and complexity strata

The million campaign targets these row shares:

| Band | Tokens | Share | Exchanges |
|---|---:|---:|---:|
| Short | 512--1,023 | 20% | 2 |
| Medium | 1,024--2,047 | 35% | 2--3 |
| Long | 2,048--3,071 | 35% | 3--5 |
| Near limit | 3,072--3,968 | 10% | 4--6 |

Within each language, complexity shares are 20% accessible, 50% general, 20%
advanced, and 10% specialist.

## Audit acceptance

When the optional instruction audit is enabled, an initial request must first
pass deterministic structure/language/control-leakage checks and a model judge.
The judge requires quality at least 4/5 plus topic and mode adherence, realism,
answerability, persona coherence, usefulness, safety, and the configured
language. Rejections retain their reason and diversity fields in
`instruction_audit/*.jsonl`; downstream response generation filters them out.

Deterministic validation rejects empty text, invalid control characters, and
confident wrong-language pairs. Short or code-heavy text and uncertain language
detection are passed to the judge rather than rejected heuristically.

For every assistant turn, the judge returns language, coherence, safety,
category, difficulty, reason, and 1--5 instruction/response quality. Acceptance
requires all of the following:

- judge acceptance, coherence, and safety;
- reported language equal to the configured lane;
- instruction quality at least 4;
- response quality at least 4.

The row is accepted only when every assistant turn is accepted. Repeatedly
malformed judge JSON fails the shard and follows normal retry semantics.

## Final retention

Finalization includes every accepted, length-valid, deduplicated row. Language
and band targets are reported as shortfall/surplus diagnostics, not destructive
caps. This behavior preserves useful rows above target and was chosen explicitly
for the million-row expansion.
