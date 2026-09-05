---
type: Runbook
title: Recovery and Idempotency
description: Atomic queue, shard, retry, restart, and incremental-expansion behavior.
tags: [recovery, sqlite, atomicity, retries]
status: stable
last_updated: 2026-09-02
confidence: high
---
# Recovery and Idempotency

## Queue ownership

Each output directory owns one `queue.sqlite3`. The queue uses WAL mode, a
60-second busy timeout, `synchronous=FULL`, and `BEGIN IMMEDIATE` for claims.
One pending row is atomically changed to running with a host/PID owner and
incremented attempt count. Two workers cannot claim the same task.

## Shard commits

Every phase writes a JSONL shard to a temporary file in the target
directory, flushes and fsyncs it, atomically replaces the destination, and
fsyncs the directory. A queue task is marked done only after that succeeds.
Instruction generation retries individual capped rows and may preserve a
nearly complete shard when no more than 2% remain bad, recording those rows in
`instruction_failures/`. Larger bursts and failures in later phases retain
whole-shard retry behavior.

Instruction audit retries malformed judge JSON per row. If all configured
parse attempts fail, it preserves every other row in the shard and records
only that row as rejected with `audit_error`; one unjudgeable row must not cause
hundreds of valid verdicts to be recomputed indefinitely.

Stopping workers therefore preserves every completed shard. Only active shard
work since its claim is repeated. Never delete completed phase files merely to
restart servers or change concurrency.

## Retry and recovery commands

Failed tasks return to pending until `servers.max_retries` is exhausted; the
million campaign allows four attempts. `koolbardi work` exits nonzero if
terminal failures remain, preventing the automatic launcher from finalizing an
incomplete campaign.

After verifying that the owning process is gone:

```bash
koolbardi reset-stale CONFIG --age-seconds 3600
```

For a deliberate immediate restart where exact workers were already validated
and terminated, `--age-seconds 0` resets their running claims. After correcting
the root cause of terminal failures:

```bash
koolbardi reset-failed CONFIG --phase instruction
koolbardi reset-failed CONFIG --phase instruction_audit
koolbardi reset-failed CONFIG --phase response
koolbardi reset-failed CONFIG --phase audit
```

Do not reset live claims or use broad process-kill patterns. On shared hosts,
identify exact campaign worker PIDs and exact named server windows first.

## Incremental expansion

`koolbardi init` uses `INSERT OR IGNORE` on `(phase, shard_key)`, so rerunning it
adds missing shard keys without replacing completed or running tasks. This
enabled the million campaign to preserve the pilot and later raise English
oversampling from 1.01 to 1.05 while generation continued.

Changing target allocation can leave an old final partial shard under the same
key and count because existing payloads are not rewritten. Consequently, queue
candidate totals can be slightly below the mathematical oversampling target.
Inspect actual queue payload totals after incremental expansion. For the active
campaign they are 2,073,646 Danish and 1,040,404 English candidates, which
retain sufficient measured acceptance margin.
