#!/usr/bin/env bash
set -euo pipefail
umask 077

version=${1:?Supply a full source commit SHA}
[[ "$version" =~ ^[0-9a-f]{40}$ ]] || { echo 'A full source commit is required' >&2; exit 2; }
root=${ZIPER_DEPLOY_ROOT:-/opt/ziper}
release="$root/releases/$version"
test -d "$release"
test -s "$release/compose.yml"
test -s "$release/image-id"
test -s "$root/private/runtime.env"
test -s "$root/private/db-ca.pem"
test -s "$root/private/cloudflared-token"

if [ -n "${ZIPER_DEPLOY_LOCK_FD:-}" ]; then
    [[ "$ZIPER_DEPLOY_LOCK_FD" =~ ^[0-9]+$ ]] && [ "$ZIPER_DEPLOY_LOCK_FD" -gt 2 ] || {
        echo 'Invalid deployment lock descriptor' >&2; exit 1;
    }
    exec 9<&"$ZIPER_DEPLOY_LOCK_FD"
    python3 - "$root/deploy.lock" <<'PY'
import os, stat, sys
try:
    expected, actual = os.stat(sys.argv[1]), os.fstat(9)
    valid = stat.S_ISREG(actual.st_mode) and (expected.st_dev, expected.st_ino) == (actual.st_dev, actual.st_ino)
except OSError:
    valid = False
if not valid:
    raise SystemExit('Deployment lock descriptor does not match the deployment lock')
PY
else
    exec 9>"$root/deploy.lock"
fi
flock -n 9 || { echo 'Another Ziper deployment is active' >&2; exit 1; }
unset COMPOSE_FILE COMPOSE_PROJECT_NAME COMPOSE_PROFILES
unset ZIPER_IMAGE ZIPER_VERSION ZIPER_PRIVATE_DIR SENTRY_RELEASE
export ZIPER_PRIVATE_DIR="$root/private"
export DOCKER_CONFIG="$root/docker-client"
test -s "$DOCKER_CONFIG/config.json"

runtime_window() {
    python3 - "$root" <<'PY'
from pathlib import Path
import sys
root = Path(sys.argv[1])
sys.path.insert(0, str(root / 'ci'))
from registry_release import ensure_runtime_window
ensure_runtime_window(root)
PY
}

# Receiver download/validation may have crossed the deployment cutoff.
runtime_window

select_release() {
    local selected=$1 expected actual
    [[ "$selected" =~ ^[0-9a-f]{40}$ ]] || return 1
    expected=$(cat "$root/releases/$selected/image-id")
    actual=$(docker image inspect --format '{{.Id}}' "ziper-server:$selected")
    [[ "$expected" =~ ^sha256:[0-9a-f]{64}$ ]] && [ "$actual" = "$expected" ] || return 1
    export ZIPER_IMAGE="ziper-server:$selected" ZIPER_VERSION="$selected"
    selected_compose="$root/releases/$selected/compose.yml"
}

compose() { docker compose -p ziper-production -f "$selected_compose" "$@"; }
ready() {
    local attempt
    for ((attempt=0; attempt<36; attempt++)); do
        if compose exec -T app curl --fail --silent --max-time 4 --output /dev/null \
                http://127.0.0.1:8080/readyz; then
            return 0
        fi
        sleep 5
    done
    return 1
}

previous=''
if [ -f "$root/current-version" ]; then
    previous=$(cat "$root/current-version")
    [[ "$previous" =~ ^[0-9a-f]{40}$ ]] || { echo 'Invalid recorded release' >&2; exit 1; }
fi
select_release "$version"
compose config --quiet
commit_release() {
    printf '%s\n' "$version" > "$root/current-version.next" && mv "$root/current-version.next" "$root/current-version"
}
if compose up -d --no-build --pull never app && ready && runtime_window && compose up -d --no-build cloudflared && commit_release; then
    printf 'Ziper release %s is ready; verify the public endpoint separately.\n' "$version"
    exit 0
fi

echo 'Ziper deployment failed app readiness or tunnel startup' >&2
if [ -n "$previous" ]; then
    if select_release "$previous" && compose up -d --no-build --pull never app && ready && compose up -d --no-build cloudflared; then
        echo 'The preceding Ziper release was restored' >&2
    else
        echo 'The preceding release did not recover; operator action is required' >&2
    fi
else
    compose stop app
fi
exit 1
