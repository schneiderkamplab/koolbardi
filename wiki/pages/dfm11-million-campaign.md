---
type: Operational Record
title: DFM11 Million Campaign
description: Configuration, pilot evidence, paths, and current state of the bilingual million-row campaign.
tags: [dfm11, campaign, danish, english]
status: draft
last_updated: 2026-09-02
confidence: high
---
# DFM11 Million Campaign

## Goal and paths

The campaign targets at least one million accepted Danish chats and one million
accepted English chats. It preserves all accepted pilot rows rather than
starting over or truncating surplus rows.

- Config: `configs/dfm11-million-a4b.yaml`
- Runtime root: `/work/mimir/HRM-Text/data/koolbardi/dfm11-million-a4b`
- Queue: `queue.sqlite3`
- Phase directories: `instruction/`, `response/`, and `audit/`
- Final output: `final.jsonl`
- Final report: `final.jsonl.report.json`
- Campaign log: `/work/mimir/HRM-Text/logs/koolbardi/million-campaign.log`
- Server logs: `/work/mimir/HRM-Text/logs/koolbardi/million-vllm/gpu{0,1,2,3}.log`

The active tmux session is `dfm11-0`; the campaign window is
`koolbardi-million`, servers are `kool-vllm-g0` through `kool-vllm-g3`, and the
monitor is `koolbardi-monitor`.

## Preserved pilot

The preserved final pilot contains 13,542 accepted rows and 29,589,951 native
rendered tokens:

| Language | Accepted rows | Tokens | Audited candidates | Usable rate |
|---|---:|---:|---:|---:|
| Danish | 5,121 | 11,545,642 | 10,542 | 48.5771% after two prompt duplicates |
| English | 8,421 | 18,044,309 | 8,500 | 99.0706% |

All accepted rows are retained. The smoke preceding the pilot produced one
Danish and one English two-exchange conversation. Independent tokenization
matched stored counts exactly: 974 Danish tokens and 887 English tokens; all
four assistant turns passed the judge.

## Candidate sizing

| Language | Accepted target | Oversampling | Actual queued candidates | Rationale |
|---|---:|---:|---:|---|
| Danish | 1,000,000 | 2.08 | 2,073,646 | Pilot required 2.0586; margin covers variance |
| English | 1,000,000 | 1.05 | 1,040,404 | 1.01 and preserved shard overlap projected only about 996K usable rows |

The English factor was increased incrementally on 2026-09-02. At the measured
99.0706% rate, the current pool projects to approximately 1.031M usable English
rows.

## Production settings

- Teacher and judge: pinned `google/gemma-4-26B-A4B-it` snapshot.
- Four B200 servers on GPUs 0--3 and ports 8100--8103.
- Server memory utilization 0.90, serving context 8,192, sequence ceiling
  3,072, automatic attention, Triton MoE, language-model-only, eager execution.
- Per-worker per-server concurrency 128.
- Workers: 24 instruction, four response, four audit.
- Instruction audit: enabled before response generation. It started with four
  workers, was raised to eight after measurements showed synchronized
  one-second request gaps and only about 48% KV-cache occupancy,
  deterministic checks followed by the same pinned teacher as judge; quality
  threshold 4/5 and maximum 256 judge tokens.
- Eight instruction-audit workers sustained 34.6 shards/minute over their first
  113 seconds, about 34% above the four-worker 25.8 shards/minute rate. No
  all-GPU zero-utilization trough occurred in a 90-second sample; KV occupancy
  was 50--61% with no waiting requests.
- The live audit was subsequently raised to twelve workers for a measured
  saturation trial. Added workers join through atomic queue claims, so no live
  shard is interrupted or discarded. Twelve workers measured 38.0 shards/minute
  over two minutes, only 9.8% above eight, while peak KV occupancy reached 99%,
  peak waiting requests reached about 580/server, and each GPU recorded roughly
  676--703 preemptions. Twelve is the ceiling for this short-output audit phase;
  do not increase it further.
- Instruction sampling: temperature 1.0, top-p 1.0, maximum 512 tokens.
- Response sampling: temperature 0.2, top-p 1.0, dynamically bounded below the
  configured 3,072-token maximum.
- Audit: temperature 0, maximum 384 tokens, up to four request/shard attempts.

## Snapshot

At 2026-09-02 11:08 Europe/Berlin, Danish initial generation was complete and
English generation was active. The queue held 4,621 completed instruction
shards, 24 running, and 1,487 pending before subsequent progress. Recent
throughput was approximately 73 shards/minute during the Danish-to-English
transition. This snapshot is historical; use `koolbardi status` for live state.

Once initial generation finishes, `run_campaign.sh` automatically queues and
runs instruction auditing, queues accepted requests for response generation,
queues and runs conversation auditing, then finalizes the complete accepted
dataset. Rejection statistics remain stratifiable by language, topic, mode,
persona source, complexity, and length band. The downstream production phases have not yet yielded
reliable million-scale ETA measurements.

## Diversity quality gate

At 2026-09-02 13:11 Europe/Berlin, all 6,132 instruction shards were complete,
but only 206 response shards were complete, four were running, and 5,922 were
pending. This is about 3.4% response-stage completion and includes 58 preserved
pilot shards.

A deterministic 100-row sample per language found 57% English travel prompts
and 96% Danish travel prompts. Because the expensive response stage is still
near its beginning, the recommended disposition is to stop this campaign,
preserve its directory unchanged for diagnosis, and initialize a new campaign
with controlled topic/persona/mode conditioning. Keep the existing temperature
and top-p settings. Existing rows may later supply a small, semantically
filtered uncontrolled slice, but must not count toward controlled topic quotas
without classification. This is a recommendation pending operator action; no
active process was stopped when it was recorded.

**Superseded later on 2026-09-02:** the recommendation was accepted. The old
coordinator was stopped, 5,918 unclaimed response shards were marked `held`,
and 210 atomically completed response shards were preserved. Four claims that
were active when the coordinator exited left no committed output and remain
visible only as stale queue state. The replacement campaign is documented in
[Controlled Diversity Generation](controlled-diversity-generation.md).
