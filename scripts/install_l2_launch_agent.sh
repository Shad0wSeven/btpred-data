#!/bin/zsh
set -eu

script_dir=${0:A:h}
source_repo=${script_dir:h}
state_dir="$HOME/Library/Application Support/btpred-l2"
publish_repo="$state_dir/publisher"
runtime_dir="$state_dir/runtime"
venv_dir="$state_dir/venv"
plist="$HOME/Library/LaunchAgents/com.btpred.l2capture.plist"
remote=$(git -C "$source_repo" remote get-url origin)

export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"

mkdir -p "$state_dir" "$runtime_dir" "${plist:h}"
if [[ ! -x "$venv_dir/bin/python" ]]; then
  /usr/bin/python3 -m venv "$venv_dir"
fi
"$venv_dir/bin/python" -m pip install \
  --disable-pip-version-check \
  -r "$source_repo/requirements-data.txt"

if [[ ! -d "$publish_repo/.git" ]]; then
  GIT_LFS_SKIP_SMUDGE=1 git clone "$remote" "$publish_repo"
else
  git -C "$publish_repo" pull --rebase origin main
fi

"$venv_dir/bin/python" - \
  "$plist" "$source_repo" "$publish_repo" "$runtime_dir" "$venv_dir" <<'PY'
import plistlib
import sys
from pathlib import Path

plist, source_repo, publish_repo, runtime_dir, venv_dir = map(Path, sys.argv[1:])
payload = {
    "Label": "com.btpred.l2capture",
    "ProgramArguments": [
        str(source_repo / "scripts" / "capture_and_publish_l2.sh"),
    ],
    "EnvironmentVariables": {
        "BTPRED_PUBLISH_REPO": str(publish_repo),
        "BTPRED_CHUNK_SECONDS": "10800",
        "BTPRED_L2_SYMBOL": "BTCFDUSD",
        "BTPRED_PYTHON": str(venv_dir / "bin" / "python"),
        "PATH": "/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin",
    },
    "RunAtLoad": True,
    "KeepAlive": True,
    "ThrottleInterval": 30,
    "ProcessType": "Background",
    "StandardOutPath": str(runtime_dir / "capture.log"),
    "StandardErrorPath": str(runtime_dir / "capture.error.log"),
}
with plist.open("wb") as output:
    plistlib.dump(payload, output)
PY

launchctl bootout "gui/$UID" "$plist" 2>/dev/null || true
launchctl bootstrap "gui/$UID" "$plist"
launchctl enable "gui/$UID/com.btpred.l2capture"

print "Installed com.btpred.l2capture"
print "Publisher checkout: $publish_repo"
print "Logs: $runtime_dir"
