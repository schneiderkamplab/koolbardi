# Koolbardi

Koolbardi is a standalone, resumable implementation of bilingual Magpie-style
synthetic conversation generation. It asks the teacher through its native chat
template to generate user requests, optionally audits requests before spending
response-generation compute, generates responses in a fresh native chat, audits
each pair, and finalizes a balanced Gemma-native JSONL dataset. Explicit
meta-requests are used because Gemma 4 A4B emits control-channel fragments when
continued directly from an unfinished user-turn prefix.

The upstream Magpie repository is useful as a behavioral reference, but it is
not a dependency, import, submodule, or vendored component of Koolbardi. This
package uses its own typed configuration, OpenAI-compatible client, SQLite WAL
queue, atomic JSONL shards, validation, and finalization code.

Detailed architecture, data-contract, serving, recovery, and campaign knowledge
lives in the [OKF v0.2 bundle](wiki/index.md).

## Safety properties

- SQLite `BEGIN IMMEDIATE` claims prevent two workers from owning one shard.
- A shard is committed only after every row succeeds; retry writes replace the
  entire shard atomically.
- The exact generation-only system prompt is retained in
  `magpie_system_prompt` but is absent from final `messages`.
- Prefixes, boundaries, stop IDs, and template hashes are derived from the
  configured tokenizer instead of hard-coded from an older Gemma release.
- Danish and English targets are reported after audit and deduplication; all
  accepted rows are retained rather than capped destructively.
- Complete rendered conversations must fit the configured context limit; data
  is rejected rather than truncated.
- Every generated user/assistant turn must return API `finish_reason=stop` and
  pass a conservative terminal-boundary check. Length-capped turns are retried
  with smaller language-calibrated word targets and are withheld if unresolved.
- When `instruction_audit.enabled` is true, only requests passing deterministic
  checks and the model judge can enter response generation.

## Installation

```bash
cd /work/mimir/HRM-Text/koolbardi
uv pip install -e '.[dev]'
```

## Pilot

Start one OpenAI-compatible vLLM server per GPU, then initialize and run each
phase. `advance-queue` is idempotent and only observes fully renamed files.

```bash
scripts/launch_vllm_servers.sh
scripts/run_campaign.sh configs/dfm11-pilot-smoke-a4b.yaml
scripts/run_campaign.sh configs/dfm11-pilot-10k-a4b.yaml
```

Use `koolbardi status CONFIG` for queue counts and `koolbardi reset-stale
CONFIG --age-seconds 3600` after verifying that abandoned workers are dead.
After correcting the underlying cause of a terminal failure, use
`koolbardi reset-failed CONFIG --phase PHASE`.

The A4B production pilot targets 10,000 accepted chats total: 5,000 Danish and
5,000 English. Every final conversation has 2--6 exchanges and is independently
rendered with the Gemma 4 tokenizer; rows above 4,096 tokens are rejected rather
than truncated.

## Concurrency

`servers.concurrency_per_server` is the per-worker HTTP connection and request
limit. `phase_workers` controls process fan-out, so the approximate aggregate
limit per server is their product. Keep the server's `--max-num-seqs` at least
as large as the intended aggregate; the launcher defaults to 3,072.

Concurrency is deliberately phase-specific. Initial user turns are short and
need thousands of live sequences to occupy the KV cache. Multi-turn response
and audit requests carry much longer prompts and therefore use fewer workers.
For the million-row campaign, the sustained settings are 24 instruction workers
and four response/audit workers at 128 requests per server per worker. Check
`vllm:kv_cache_usage_perc`, running/waiting requests, preemptions, and generated
token throughput before increasing these settings further.
