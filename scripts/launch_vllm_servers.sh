#!/usr/bin/env bash
set -euo pipefail

MODEL=${MODEL:-/work/dfm/HRM-Text/data/models/google/gemma-4-31B-it-fresh-20260604}
LOG_DIR=${LOG_DIR:-/work/dfm/HRM-Text/logs/koolbardi/vllm}
GPU_MEMORY_UTILIZATION=${GPU_MEMORY_UTILIZATION:-0.70}
CONDA_ENV=${CONDA_ENV:-audit}
mkdir -p "$LOG_DIR"

for gpu in 0 1 2 3 4 5 6 7; do
  port=$((8100 + gpu))
  echo "Starting Gemma 4 31B server on GPU ${gpu}, port ${port}"
  CUDA_VISIBLE_DEVICES=$gpu setsid conda run --no-capture-output -n "$CONDA_ENV" \
    vllm serve "$MODEL" \
      --served-model-name "$MODEL" \
      --port "$port" \
      --gpu-memory-utilization "$GPU_MEMORY_UTILIZATION" \
      --trust-remote-code \
      >"$LOG_DIR/gpu${gpu}.log" 2>&1 &
  echo $! >"$LOG_DIR/gpu${gpu}.pid"
done

