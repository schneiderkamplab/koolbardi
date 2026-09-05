---
type: Decision Record
title: Decision History
description: Superseded Koolbardi approaches and the evidence behind their replacement.
tags: [decisions, failures, superseded]
status: stable
last_updated: 2026-09-02
confidence: high
---
# Decision History

## Unfinished native user completion

**Superseded, 2026-09-02.** Direct continuation from an unfinished Gemma 4 user
turn was tested with rendered string prompts and exact token-ID prompts. The
26B-A4B checkpoint emitted control-channel fragments such as `own-`, `way-`,
and `thought` before or instead of a useful request. Koolbardi therefore uses
explicit native-chat meta-requests to generate initial and follow-up user turns.
These meta-requests are not included in final training messages.

## Token counting through BatchEncoding length

**Superseded, 2026-09-02.** `len(BatchEncoding)` returned `2`, the number of
mapping fields, and did not measure conversation tokens. Exact accounting now
uses `return_dict=False`, normalizes supported Transformers return layouts, and
counts the resulting token IDs. Stored smoke counts were verified by independent
re-rendering.

## Forced FlashAttention

**Rejected, 2026-09-02.** Forcing the vLLM FlashAttention backend selected an
FA2 path incompatible with Gemma 4's 512-dimensional global heads. Automatic
heterogeneous attention selection works. `--moe-backend triton` controls only
the MoE implementation and remains enabled.

## One fixed generation budget

**Superseded, 2026-09-02.** A one-turn 3,072-token answer allowance could consume
the entire row and prevent meaningful follow-ups. Current response generation
re-renders before every turn and reserves budget across all remaining user and
assistant turns. It prefers a complete shorter conversation to truncation.

## Destructive target capping

**Rejected, 2026-09-02.** Final language/band quotas are diagnostics, not slices.
All accepted, length-valid, deduplicated rows are retained, including pilot rows
and target surplus.

## Concurrency sequence

**Superseded settings, 2026-09-02.** A 128-sequence server ceiling and later 512
short requests underused the available KV cache. Raising to 4,096 delivered high
active-window token throughput but eventually filled KV to 99--100%, queued
work, and caused substantial preemption. The measured 3,072 setting matched
completed-shard throughput with 78--80% peak KV and no preemption, and is the
current initial-generation default. Response and audit remain at 512 aggregate
requests/server pending phase-specific measurement.

