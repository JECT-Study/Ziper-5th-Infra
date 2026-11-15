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
if [ -e "$root/ops/recovery-lease.json" ] || [ -L "$root/ops/recovery-lease.json" ]; then
    echo 'A Ziper recovery lease must be resolved before deployment' >&2
    exit 1
fi

# The receiver passes the bundle it just stored; a manual redeploy reuses the recorded one.
config_valid() {
    [[ "$1" =~ ^[0-9a-f]{64}$ ]] || return 1
    local name
    for name in application.properties migration.properties db-ca.pem; do
        test -s "$root/private/config/$1/$name" || return 1
    done
}
previous_config=''
if [ -f "$root/current-config" ]; then
    previous_config=$(cat "$root/current-config")
    config_valid "$previous_config" || { echo 'Invalid recorded configuration bundle' >&2; exit 1; }
fi
config=${ZIPER_CONFIG_ID:-$previous_config}
config_valid "$config" || { echo 'A stored configuration bundle is required' >&2; exit 2; }
unset COMPOSE_FILE COMPOSE_PROJECT_NAME COMPOSE_PROFILES
unset ZIPER_IMAGE ZIPER_VERSION ZIPER_PRIVATE_DIR ZIPER_CONFIG_DIR SENTRY_RELEASE
export ZIPER_PRIVATE_DIR="$root/private"
export ZIPER_CONFIG_DIR="$root/private/config/$config"
# Docker Desktop re-creates WSL bind sources only after the distro proxy starts, so a boot-time
# restart of a WSL file bind fails. Named volumes live in the Docker VM and survive that restart.
export ZIPER_CONFIG_VOLUME="ziper-config-$config"
tunnel_hash=$(sha256sum < "$root/private/cloudflared-token" | cut -c1-24)
export ZIPER_TUNNEL_VOLUME="ziper-tunnel-$tunnel_hash"
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

# A volume is a derived copy of an immutable host source and is checked byte for byte.
volume_matches() {
    local name=$1 source=$2 helper copy status
    copy=$(mktemp -d)
    helper=$(docker create --network none --entrypoint true -v "$name:/source:ro" "$ZIPER_IMAGE") || { rm -rf "$copy"; return 1; }
    status=0
    docker cp "$helper:/source/." "$copy/" >/dev/null || status=1
    docker rm "$helper" >/dev/null || status=1
    [ "$status" -eq 0 ] && diff -r -q "$source" "$copy" >/dev/null || status=1
    rm -rf "$copy"
    return "$status"
}
ensure_volume() {
    local name=$1 source=$2 helper
    if docker volume inspect "$name" >/dev/null 2>&1; then
        volume_matches "$name" "$source" && return 0
        # Only an unused volume is replaced; Docker refuses removal while a container references it.
        docker volume rm "$name" >/dev/null || { echo "Runtime volume differs and is in use: $name" >&2; return 1; }
    fi
    docker volume create --label ziper.managed=true "$name" >/dev/null || return 1
    if helper=$(docker create --network none --entrypoint true -v "$name:/target" "$ZIPER_IMAGE"); then
        docker cp "$source/." "$helper:/target" >/dev/null && docker rm "$helper" >/dev/null && volume_matches "$name" "$source" && return 0
        docker rm "$helper" >/dev/null 2>&1 || true
    fi
    docker volume rm "$name" >/dev/null 2>&1 || true
    echo "Runtime volume could not be populated: $name" >&2
    return 1
}
tunnel_source=$(mktemp -d)
trap 'rm -rf "$tunnel_source"' EXIT
cp "$root/private/cloudflared-token" "$tunnel_source/tunnel-token"
chmod 0444 "$tunnel_source/tunnel-token"
runtime_volumes() {
    ensure_volume "$ZIPER_CONFIG_VOLUME" "$ZIPER_CONFIG_DIR" && ensure_volume "$ZIPER_TUNNEL_VOLUME" "$tunnel_source"
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
    printf '%s\n' "$config" > "$root/current-config.next" && mv "$root/current-config.next" "$root/current-config" \
        && printf '%s\n' "$version" > "$root/current-version.next" && mv "$root/current-version.next" "$root/current-version"
}
restore_config_record() {
    if [ -n "$previous_config" ]; then
        printf '%s\n' "$previous_config" > "$root/current-config.next" && mv "$root/current-config.next" "$root/current-config"
    else
        rm -f "$root/current-config"
    fi
}
if runtime_volumes && compose up -d --no-build --pull never app && ready && runtime_window && compose up -d --no-build cloudflared && commit_release; then
    printf 'Ziper release %s is ready; verify the public endpoint separately.\n' "$version"
    exit 0
fi

echo 'Ziper deployment failed app readiness or tunnel startup' >&2
# The release record may have failed after the configuration record moved.
restore_config_record || echo 'The configuration record could not be restored' >&2
if [ -n "$previous_config" ]; then
    export ZIPER_CONFIG_DIR="$root/private/config/$previous_config" ZIPER_CONFIG_VOLUME="ziper-config-$previous_config"
fi
if [ -n "$previous" ]; then
    if select_release "$previous" && runtime_volumes && compose up -d --no-build --pull never app && ready && compose up -d --no-build cloudflared; then
        echo 'The preceding Ziper release was restored' >&2
    else
        echo 'The preceding release did not recover; operator action is required' >&2
    fi
else
    compose stop app
fi
exit 1
