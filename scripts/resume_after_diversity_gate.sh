#!/usr/bin/env bash
set -euo pipefail

CONFIG=${1:?usage: resume_after_diversity_gate.sh CONFIG REPORT}
REPORT=${2:?usage: resume_after_diversity_gate.sh CONFIG REPORT}
PYTHON=${PYTHON:-/work/mimir/.home/miniforge3/envs/audit/bin/python}
KOOLBARDI=${KOOLBARDI:-/work/mimir/.home/miniforge3/envs/audit/bin/koolbardi}

readarray -t paths < <("$PYTHON" - "$CONFIG" <<'PY'
from pathlib import Path
import sys
from koolbardi.config import load_config
c = load_config(Path(sys.argv[1]))
print(c.root)
print(c.root / "queue.sqlite3")
print(c.root / "final.jsonl")
PY
)
ROOT=${paths[0]}
QUEUE=${paths[1]}
FINAL=${paths[2]}
LOCK="$ROOT/resume-after-gate.lock"

exec 9>"$LOCK"
flock -n 9 || { echo "Another gate-resume watcher owns $LOCK"; exit 1; }

echo "Waiting for diversity report: $REPORT"
while [[ ! -s "$REPORT" ]]; do sleep 60; done
"$PYTHON" - "$REPORT" <<'PY'
import json, sys
r=json.load(open(sys.argv[1]))
for language, lane in r["lanes"].items():
    assert lane["topics"]["unique"] >= 130, (language, "topics")
    assert lane["modes"]["unique"] == 20, (language, "modes")
    assert lane["topics"]["normalized_entropy"] >= 0.99, (language, "topic entropy")
    assert lane["modes"]["normalized_entropy"] >= 0.99, (language, "mode entropy")
    assert lane["sample_near_duplicates"]["0.75"]["rows_with_neighbor"] <= 10, (language, "duplicates")
print("Diversity gate passed")
PY

echo "Waiting for the gate tranche to finish audit/finalization: $FINAL"
while [[ ! -s "$FINAL" ]]; do sleep 60; done

released=$("$PYTHON" - "$QUEUE" <<'PY'
import sqlite3, sys
with sqlite3.connect(sys.argv[1], timeout=60) as c:
    c.execute("PRAGMA busy_timeout=60000")
    c.execute("BEGIN IMMEDIATE")
    running=c.execute("SELECT COUNT(*) FROM tasks WHERE status='running'").fetchone()[0]
    if running:
        raise SystemExit(f"refusing to release held work while {running} tasks are running")
    count=c.execute(
        "UPDATE tasks SET status='pending', error=NULL WHERE phase='instruction' AND status='held'"
    ).rowcount
    c.commit()
print(count)
PY
)
echo "Released $released held instruction shards; resuming the full campaign."
exec scripts/run_campaign.sh "$CONFIG"
