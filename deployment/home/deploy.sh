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

exec 9>"$root/deploy.lock"
flock -n 9 || { echo 'Another Ziper deployment is active' >&2; exit 1; }
unset COMPOSE_FILE COMPOSE_PROJECT_NAME COMPOSE_PROFILES
unset ZIPER_IMAGE ZIPER_VERSION ZIPER_PRIVATE_DIR SENTRY_RELEASE
export ZIPER_PRIVATE_DIR="$root/private"
export DOCKER_CONFIG="$root/docker-client"
test -s "$DOCKER_CONFIG/config.json"

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
if compose up -d --no-build --pull never app && ready; then
    compose up -d --no-build cloudflared
    printf '%s\n' "$version" > "$root/current-version.next"
    mv "$root/current-version.next" "$root/current-version"
    printf 'Ziper release %s is ready; verify the public endpoint separately.\n' "$version"
    exit 0
fi

echo 'Ziper deployment failed readiness verification' >&2
if [ -n "$previous" ] && [ "$previous" != "$version" ]; then
    select_release "$previous"
    if compose up -d --no-build --pull never app && ready; then
        echo 'The preceding Ziper release was restored' >&2
    else
        echo 'The preceding release did not recover; operator action is required' >&2
    fi
else
    compose stop app
fi
exit 1
