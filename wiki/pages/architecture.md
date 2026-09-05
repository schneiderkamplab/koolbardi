---
type: Technical Reference
title: Architecture
description: Components and control flow of the standalone Koolbardi pipeline.
tags: [architecture, pipeline, magpie]
status: stable
last_updated: 2026-09-02
confidence: high
---
# Architecture

Koolbardi is a standalone implementation of bilingual Magpie-style synthetic
conversation generation. Magpie is a behavioral reference, not a runtime
dependency, vendored component, import, or submodule.

## Components

- `config.py`: validated Pydantic configuration for language lanes, length
  bands, sampling, servers, and phase-specific worker counts.
- `template.py`: derives boundaries and hashes from the configured native chat
  template and provides version-tolerant exact token rendering.
- `client.py`: persistent per-server `httpx.AsyncClient` pools, semaphores,
  retries, and OpenAI-compatible chat/completion calls.
- `queue.py`: SQLite WAL queue with atomic claims and retry state.
- `pipeline.py`: initialization, four phase processors, downstream queueing,
  and finalization.
- `validation.py`: deterministic language and structural checks before model
  judging.
- `io.py`: fsynced temporary-file writes followed by atomic replacement.
- `cli.py`: Typer commands for operating and recovering campaigns.

## Four Stages

### Initial instruction generation

The configured teacher generates only the first user request. An explicit
meta-request supplies the language, complexity stratum, target length band, and
desired exchange count. This metadata is retained for provenance but is not
part of the final conversation.

### Instruction audit

This optional pre-response gate first rejects empty, malformed, confidently
wrong-language, implausibly short, or generation-control-leaking requests. A
model judge then checks language, topic and interaction-mode adherence, realism,
answerability, persona coherence, safety, and training usefulness. Audit files
retain accepted and rejected rows plus reasons; only accepted rows enter the
response phase. This gate avoids spending long-response compute on unsuitable
requests and supports rejection analysis by topic, mode, and language.

### Response generation

The teacher answers the first request, generates context-aware follow-up user
turns, and answers them until the desired 2--6 exchanges are complete. Before
each generation, Koolbardi renders the native chat history and allocates the
remaining token budget fairly across future user and assistant turns. A
temporary completeness instruction asks assistant turns to finish within their
budget; it is absent from final `messages`.

### Audit and finalization

Every assistant turn first passes deterministic checks and then a model judge.
A conversation is accepted only if every assistant turn passes. Finalization
deduplicates normalized first-user prompts, independently re-renders token
counts, preserves all accepted rows, and writes a report alongside the final
JSONL.

The campaign launcher runs these stages sequentially and automatically calls
`advance-queue` between them. Phase worker counts differ because initial turns
are short while response and audit requests contain longer histories.
