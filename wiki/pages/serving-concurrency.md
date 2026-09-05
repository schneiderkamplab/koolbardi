---
type: Technical Reference
title: Serving and Concurrency
description: Verified Gemma 4 A4B vLLM settings and measured concurrency tradeoffs.
tags: [vllm, gemma, performance, concurrency]
status: stable
last_updated: 2026-09-02
confidence: high
---
# Serving and Concurrency

## Verified Gemma 4 A4B setup

The active model is the pinned `google/gemma-4-26B-A4B-it` snapshot. Each B200
server uses:

- `--gpu-memory-utilization 0.90`;
- `--max-model-len 8192` because audit prompts include transcripts;
- `--max-num-seqs 3072` for initial-turn production;
- `--language-model-only`;
- `--enforce-eager`;
- `--moe-backend triton`.

Use automatic heterogeneous attention selection. Gemma 4 has 256-dimensional
local and 512-dimensional global attention heads. Forcing FlashAttention chose
an incompatible FA2 path and failed on the global heads. Triton is specified
only for the MoE backend. The larger server context does not relax the final
4,096-token data limit.

The server reports approximately 523,730 KV-cache tokens per GPU and maximum
concurrency of 63.93 requests when every request consumes the full 8,192-token
serving context. Actual short initial requests permit much higher sequence
concurrency.

## Client capacity

`servers.concurrency_per_server` is a per-worker semaphore and persistent HTTP
connection-pool limit. Approximate aggregate request capacity per server is:

```text
concurrency_per_server * phase_workers.<phase>
```

The million campaign uses 128 per worker, with 24 instruction workers and four
response/audit workers. This yields 3,072 short initial requests/server and 512
longer response or audit requests/server. Both the vLLM sequence ceiling and
HTTP client connection pools must allow the intended aggregate.

## Measurements

| Setting | Active sequences/GPU | KV behavior | Generated throughput | Completed work | Outcome |
|---|---:|---:|---:|---:|---|
| 128 | about 100 observed | 20--24% on longer pilot work | about 4.5K--5.1K tok/s | not retained | Superseded |
| 512 | about 512 | 11.7% peak for short initial turns | about 8K--10K tok/s | 51--58 shards/min later at higher load | Superseded |
| 4,096 | 4,090--4,095 | initially 81--83%, eventually 99--100% | 21.6K--23.2K tok/s during active windows | about 51--58 shards/min | Upper bound; waiting and tens of thousands of preemptions |
| 3,072 | about 3,072 | 78--80% peak, 41% mean including synchronized gaps | **18.3K tok/s/GPU sustained** | **55.4 512-row shards/min** | Adopted |

The 3,072 measurement covered 182 seconds and included shard-boundary idle
periods. It had zero waiting requests and zero preemptions. It matched 4,096's
useful row throughput without recomputation pressure.

## Interpretation

Do not optimize for literal 100% KV occupancy or point-in-time `nvidia-smi`
compute utilization. A4B autoregressive decode activates only part of the MoE,
uses routing and smaller GEMMs, and currently runs eagerly without CUDA graphs.
Synchronized 512-row workers also produce a sawtooth: servers fill, drain, and
briefly idle while all workers atomically write and claim new shards.

For a new phase, increase concurrency while observing sustained generated
tokens/s, completed rows/min, waiting requests, preemptions, and host memory.
Initial prompts and transcript-heavy response/audit work require different
limits. Do not copy 3,072 into response or audit without a new measurement.

