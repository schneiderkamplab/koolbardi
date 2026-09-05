#!/usr/bin/env bash
set -euo pipefail

CONFIG=${1:?usage: run_phase_workers.sh CONFIG PHASE [WORKERS]}
PHASE=${2:?usage: run_phase_workers.sh CONFIG PHASE [WORKERS]}
WORKERS=${3:-8}
REPO_ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
LOG_DIR=${LOG_DIR:-$REPO_ROOT/logs/koolbardi/workers}
mkdir -p "$LOG_DIR"

for ((worker=0; worker<WORKERS; worker++)); do
  echo "Starting ${PHASE} worker ${worker}"
  setsid koolbardi work "$CONFIG" --phase "$PHASE" \
    >"$LOG_DIR/${PHASE}-${worker}.log" 2>&1 &
  echo $! >"$LOG_DIR/${PHASE}-${worker}.pid"
done
