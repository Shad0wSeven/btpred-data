#!/bin/zsh
set -eu

script_dir=${0:A:h}
source_repo=${script_dir:h}
state_dir="$HOME/Library/Application Support/btpred-kalshi-15m"
app_dir="$state_dir/app"
publish_repo="$state_dir/publisher"
runtime_dir="$state_dir/runtime"
plist="$HOME/Library/LaunchAgents/com.btpred.kalshi15m.plist"
remote=$(git -C "$source_repo" remote get-url origin)

export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"

mkdir -p "$app_dir/scripts" "$runtime_dir" "${plist:h}"
cp "$source_repo/scripts/capture_kalshi_15m.py" "$app_dir/scripts/"
cp "$source_repo/scripts/capture_and_publish_kalshi_15m.sh" "$app_dir/scripts/"
chmod +x "$app_dir/scripts/capture_and_publish_kalshi_15m.sh"

if [[ ! -d "$publish_repo/.git" ]]; then
  GIT_CLONE_PROTECTION_ACTIVE=false GIT_LFS_SKIP_SMUDGE=1 \
    git clone "$remote" "$publish_repo"
else
  GIT_CLONE_PROTECTION_ACTIVE=false GIT_LFS_SKIP_SMUDGE=1 \
    git -C "$publish_repo" checkout -f main
  GIT_LFS_SKIP_SMUDGE=1 git -C "$publish_repo" pull --rebase origin main
fi

/usr/bin/python3 - "$plist" "$app_dir" "$publish_repo" "$runtime_dir" <<'PY'
import plistlib
import sys
from pathlib import Path

plist, app_dir, publish_repo, runtime_dir = map(Path, sys.argv[1:])
payload = {
    "Label": "com.btpred.kalshi15m",
    "ProgramArguments": [str(app_dir / "scripts" / "capture_and_publish_kalshi_15m.sh")],
    "EnvironmentVariables": {
        "BTPRED_PUBLISH_REPO": str(publish_repo),
        "BTPRED_CHUNK_SECONDS": "10800",
        "BTPRED_PYTHON": "/usr/bin/python3",
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
launchctl enable "gui/$UID/com.btpred.kalshi15m"

print "Installed com.btpred.kalshi15m"
print "Publisher checkout: $publish_repo"
print "Logs: $runtime_dir"
