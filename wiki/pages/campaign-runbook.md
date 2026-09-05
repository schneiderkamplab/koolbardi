---
type: Runbook
title: Campaign Runbook
description: Commands for installing, serving, running, monitoring, and finalizing Koolbardi campaigns.
tags: [operations, vllm, generation]
status: stable
last_updated: 2026-09-03
confidence: high
---
# Campaign Runbook

## Install

Use the environment intended to operate the OpenAI-compatible servers and
workers:

```bash
cd /work/mimir/HRM-Text/koolbardi
uv pip install -e '.[dev]'
```

On the current host, the working Python and CLI are in the `audit` conda
environment under `/work/mimir/.home/miniforge3/envs/audit`.

## Start servers

The launcher defaults to GPUs 0--3, ports 8100--8103, 90% vLLM memory
utilization, 8,192 serving tokens, and 3,072 sequences:

```bash
cd /work/mimir/HRM-Text/koolbardi
scripts/launch_vllm_servers.sh
```

Wait until every `/health` endpoint succeeds before starting clients. For
long-running operations, one named tmux window per server makes ownership and
targeted shutdown explicit.

## Run automatically

```bash
cd /work/mimir/HRM-Text/koolbardi
scripts/run_campaign.sh configs/dfm11-million-a4b.yaml
```

The script idempotently initializes instruction shards, runs all instruction
workers, advances and runs response shards, advances and runs audits, and then
finalizes `final.jsonl`. Worker fan-out comes from `phase_workers` in the typed
configuration. Queue advancement uses one atomic bulk SQLite transaction; do
not replace it with one durable transaction per shard on shared storage.

When `final_selection` is configured, the launcher also runs
`select-responses` before response workers and `select-audits` before audit
workers. These commands atomically hold surplus tasks and write deterministic
selection receipts. They are safe to rerun after a restart or after increasing
the target; do not manually release every held task.

Instruction and response audits use the OpenAI-compatible strict JSON Schema
response format. This prevents malformed judge JSON rather than spending
application-level retries repairing it. Transport failures still use bounded
client retries. Natural-language response generation remains unconstrained by
a JSON schema and retries only incomplete/capped prose with a smaller word
budget.

## Run manually

```bash
koolbardi init configs/dfm11-million-a4b.yaml
koolbardi work configs/dfm11-million-a4b.yaml --phase instruction
koolbardi advance-queue configs/dfm11-million-a4b.yaml
koolbardi select-responses configs/dfm11-million-a4b.yaml
koolbardi work configs/dfm11-million-a4b.yaml --phase response
koolbardi advance-queue configs/dfm11-million-a4b.yaml
koolbardi select-audits configs/dfm11-million-a4b.yaml
koolbardi work configs/dfm11-million-a4b.yaml --phase audit
koolbardi finalize-dataset configs/dfm11-million-a4b.yaml \
  -o /work/mimir/HRM-Text/data/koolbardi/dfm11-million-a4b/final.jsonl
```

`scripts/run_phase_workers.sh` starts a requested number of detached workers
for one phase. Prefer the automatic launcher unless deliberately operating a
single phase.

## Monitor

```bash
koolbardi status configs/dfm11-million-a4b.yaml
scripts/monitor_campaign.sh configs/dfm11-million-a4b.yaml 60
```

Also inspect each server's `/metrics` endpoint. The important vLLM metrics are
`vllm:generation_tokens_total`, `vllm:kv_cache_usage_perc`, running and waiting
requests, and cumulative preemptions. Completed rows or shards per wall-clock
minute are the final throughput signal.

Keep non-available host memory below 80%. On the current machine, only GPUs
0--3 belong to this campaign; do not inspect, signal, or terminate unrelated
GPU 4--7 processes.

## Verify

```bash
python -m pytest -q
python scripts/validate_okf.py wiki
```
