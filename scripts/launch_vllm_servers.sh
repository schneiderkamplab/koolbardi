#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
MODEL=${MODEL:-google/gemma-4-26B-A4B-it}
SERVED_MODEL_NAME=${SERVED_MODEL_NAME:-$MODEL}
LOG_DIR=${LOG_DIR:-$REPO_ROOT/logs/koolbardi/vllm}
GPU_MEMORY_UTILIZATION=${GPU_MEMORY_UTILIZATION:-0.90}
GPUS=${GPUS:-0,1,2,3}
PORT_BASE=${PORT_BASE:-8100}
MAX_MODEL_LEN=${MAX_MODEL_LEN:-8192}
MAX_NUM_SEQS=${MAX_NUM_SEQS:-3072}
LANGUAGE_MODEL_ONLY=${LANGUAGE_MODEL_ONLY:-1}
ENFORCE_EAGER=${ENFORCE_EAGER:-1}
MOE_BACKEND=${MOE_BACKEND:-triton}
CONDA_ENV=${CONDA_ENV:-audit}
mkdir -p "$LOG_DIR"

extra_args=()
if [[ "$LANGUAGE_MODEL_ONLY" == "1" ]]; then
  extra_args+=(--language-model-only)
fi
if [[ "$ENFORCE_EAGER" == "1" ]]; then
  extra_args+=(--enforce-eager)
fi
if [[ -n "$MOE_BACKEND" ]]; then
  extra_args+=(--moe-backend "$MOE_BACKEND")
fi

IFS=',' read -ra GPU_IDS <<< "$GPUS"
for gpu in "${GPU_IDS[@]}"; do
  port=$((PORT_BASE + gpu))
  echo "Starting ${MODEL} on GPU ${gpu}, port ${port}"
  CUDA_VISIBLE_DEVICES=$gpu setsid conda run --no-capture-output -n "$CONDA_ENV" \
    vllm serve "$MODEL" \
      --served-model-name "$SERVED_MODEL_NAME" \
      --port "$port" \
      --gpu-memory-utilization "$GPU_MEMORY_UTILIZATION" \
      --max-model-len "$MAX_MODEL_LEN" \
      --max-num-seqs "$MAX_NUM_SEQS" \
      --trust-remote-code \
      "${extra_args[@]}" \
      >"$LOG_DIR/gpu${gpu}.log" 2>&1 &
  echo $! >"$LOG_DIR/gpu${gpu}.pid"
done
