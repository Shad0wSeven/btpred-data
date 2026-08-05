#!/bin/zsh
set -eu

script_dir=${0:A:h}
source_repo=${script_dir:h}
publish_repo=${BTPRED_PUBLISH_REPO:-"$source_repo"}
chunk_seconds=${BTPRED_CHUNK_SECONDS:-10800}
python_bin=${BTPRED_PYTHON:-python3}
data_dir="$publish_repo/kalshi_15m_live"

export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"

mkdir -p "$data_dir"
GIT_LFS_SKIP_SMUDGE=1 git -C "$publish_repo" pull --rebase origin main
git -C "$publish_repo" push origin main || true

started=$(date -u +%Y%m%dT%H%M%SZ)
relative_path="kalshi_15m_live/KXBTC15M-${started}-${chunk_seconds}s.jsonl.gz"
output_path="$publish_repo/$relative_path"

"$python_bin" "$source_repo/scripts/capture_kalshi_15m.py" \
  --seconds "$chunk_seconds" \
  --poll-ms 1000 \
  --depth 100 \
  --output "$output_path"

gzip -t "$output_path"
snapshots=$(gzip -dc "$output_path" | grep -c '"type":"snapshot"' | tr -d ' ')
if (( snapshots < chunk_seconds / 2 )); then
  print -u2 "capture has only $snapshots snapshots; not publishing"
  exit 1
fi

GIT_LFS_SKIP_SMUDGE=1 git -C "$publish_repo" pull --rebase origin main
git -C "$publish_repo" add -- "$relative_path"
git -C "$publish_repo" commit --only \
  -m "Add KXBTC15M live capture ${started}" \
  -- "$relative_path"
git -C "$publish_repo" push origin main

print "published $relative_path ($snapshots snapshots)"
