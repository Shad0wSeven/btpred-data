#!/bin/zsh
set -eu

script_dir=${0:A:h}
source_repo=${script_dir:h}
publish_repo=${BTPRED_PUBLISH_REPO:-"$source_repo"}
chunk_seconds=${BTPRED_CHUNK_SECONDS:-10800}
symbol=${BTPRED_L2_SYMBOL:-BTCFDUSD}
python_bin=${BTPRED_PYTHON:-python3}
data_dir="$publish_repo/granular/spot_l2"

export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"

mkdir -p "$data_dir"
git -C "$publish_repo" pull --rebase origin main
git -C "$publish_repo" push origin main || true

started=$(date -u +%Y%m%dT%H%M%SZ)
relative_path="granular/spot_l2/${symbol}-depth-${started}-${chunk_seconds}s.jsonl.gz"
output_path="$publish_repo/$relative_path"

"$python_bin" "$source_repo/scripts/capture_spot_l2.py" \
  --symbol "$symbol" \
  --seconds "$chunk_seconds" \
  --output "$output_path"

gzip -t "$output_path"
records=$(gzip -dc "$output_path" | wc -l | tr -d ' ')
if (( records < 2 )); then
  print -u2 "capture has only $records record(s); not publishing"
  exit 1
fi

git -C "$publish_repo" pull --rebase origin main
git -C "$publish_repo" add -- "$relative_path"
git -C "$publish_repo" commit --only \
  -m "Add ${symbol} L2 capture ${started}" \
  -- "$relative_path"
git -C "$publish_repo" push origin main

print "published $relative_path ($records records)"
