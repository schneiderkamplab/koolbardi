#!/usr/bin/env bash
set -euo pipefail

CONFIG=${1:?usage: run_campaign.sh CONFIG [OUTPUT]}
OUTPUT=${2:-}
PYTHON=${PYTHON:-/work/mimir/.home/miniforge3/envs/audit/bin/python}
KOOLBARDI=${KOOLBARDI:-/work/mimir/.home/miniforge3/envs/audit/bin/koolbardi}

phase_workers() {
  "$PYTHON" - "$CONFIG" "$1" <<'PY'
from pathlib import Path
import sys
from koolbardi.config import load_config

config = load_config(Path(sys.argv[1]))
print(getattr(config.phase_workers, sys.argv[2]))
PY
}

run_phase() {
  local phase=$1
  local workers
  local pids=()
  local rc=0
  workers=$(phase_workers "$phase")
  echo "Starting $workers $phase workers..."
  for ((worker=0; worker<workers; worker++)); do
    "$KOOLBARDI" work "$CONFIG" --phase "$phase" &
    pids+=("$!")
  done
  for pid in "${pids[@]}"; do
    wait "$pid" || rc=1
  done
  return "$rc"
}

if [[ -z "$OUTPUT" ]]; then
  OUTPUT=$($PYTHON - "$CONFIG" <<'PY'
from pathlib import Path
import sys
from koolbardi.config import load_config

config = load_config(Path(sys.argv[1]))
print(config.root / "final.jsonl")
PY
  )
fi

echo "Initializing instruction shards..."
"$KOOLBARDI" init "$CONFIG"

echo "Generating initial user turns..."
run_phase instruction

if "$PYTHON" - "$CONFIG" <<'PY'
from pathlib import Path
import sys
from koolbardi.config import load_config
raise SystemExit(0 if load_config(Path(sys.argv[1])).instruction_audit.enabled else 1)
PY
then
  echo "Queueing and auditing user instructions before response generation..."
  "$KOOLBARDI" advance-queue "$CONFIG"
  run_phase instruction_audit
fi

echo "Queueing and generating multi-turn responses..."
"$KOOLBARDI" advance-queue "$CONFIG"
"$KOOLBARDI" select-responses "$CONFIG"
run_phase response

echo "Queueing and auditing every assistant turn..."
"$KOOLBARDI" advance-queue "$CONFIG"
"$KOOLBARDI" select-audits "$CONFIG"
run_phase audit

echo "Finalizing balanced 4K-safe dataset..."
"$KOOLBARDI" finalize-dataset "$CONFIG" --output "$OUTPUT"
echo "Finished: $OUTPUT"
