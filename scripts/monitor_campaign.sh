#!/usr/bin/env bash
set -euo pipefail

CONFIG=${1:?usage: monitor_campaign.sh CONFIG [INTERVAL_SECONDS]}
INTERVAL=${2:-60}
KOOLBARDI=${KOOLBARDI:-/work/mimir/.home/miniforge3/envs/audit/bin/koolbardi}

while true; do
  clear
  date --iso-8601=seconds
  awk '
    /MemTotal:/ { total=$2 }
    /MemAvailable:/ { available=$2 }
    END {
      used=total-available
      printf "Host non-available memory: %.1f / %.1f GiB (%.1f%%)\n", used/1048576, total/1048576, 100*used/total
      if (100*used/total >= 80) print "CRITICAL: host memory threshold reached"
    }
  ' /proc/meminfo
  echo
  nvidia-smi -i 0,1,2,3 \
    --query-gpu=index,memory.used,memory.total,utilization.gpu \
    --format=csv,noheader
  echo
  "$KOOLBARDI" status "$CONFIG" || echo "Queue status temporarily unavailable (SQLite writer active)"
  sleep "$INTERVAL"
done
