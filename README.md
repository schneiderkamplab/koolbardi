# Koolbardi

Koolbardi is a standalone, resumable implementation of bilingual Magpie-style
synthetic conversation generation. It generates user requests from a model's
unfinished native user-turn prefix, generates responses in a fresh native chat,
audits each pair, and finalizes a balanced Gemma-native JSONL dataset.

The upstream Magpie repository is useful as a behavioral reference, but it is
not a dependency, import, submodule, or vendored component of Koolbardi. This
package uses its own typed configuration, OpenAI-compatible client, SQLite WAL
queue, atomic JSONL shards, validation, and finalization code.

## Safety properties

- SQLite `BEGIN IMMEDIATE` claims prevent two workers from owning one shard.
- A shard is committed only after every row succeeds; retry writes replace the
  entire shard atomically.
- The exact generation-only system prompt is retained in
  `magpie_system_prompt` but is absent from final `messages`.
- Prefixes, boundaries, stop IDs, and template hashes are derived from the
  configured tokenizer instead of hard-coded from an older Gemma release.
- Danish and English quotas are applied after audit and deduplication.
- Complete rendered conversations must fit the configured context limit; data
  is rejected rather than truncated.

## Installation

```bash
cd /work/dfm/HRM-Text/koolbardi
uv pip install -e '.[dev]'
```

## Pilot

Start one OpenAI-compatible vLLM server per GPU, then initialize and run each
phase. `advance-queue` is idempotent and only observes fully renamed files.

```bash
scripts/launch_vllm_servers.sh
koolbardi init configs/dfm11-pilot.yaml
scripts/run_phase_workers.sh configs/dfm11-pilot.yaml instruction 8
koolbardi advance-queue configs/dfm11-pilot.yaml
scripts/run_phase_workers.sh configs/dfm11-pilot.yaml response 8
koolbardi advance-queue configs/dfm11-pilot.yaml
scripts/run_phase_workers.sh configs/dfm11-pilot.yaml audit 8
koolbardi finalize-dataset configs/dfm11-pilot.yaml \
  --output ../data/koolbardi/dfm11-pilot/final.jsonl
```

Use `koolbardi status CONFIG` for queue counts and `koolbardi reset-stale
CONFIG --age-seconds 3600` after verifying that abandoned workers are dead.

The production config is intentionally provisional. Run and inspect the 10,000
accepted rows per language pilot before freezing temperatures, category caps,
oversampling factors, or the million-row production campaign.

