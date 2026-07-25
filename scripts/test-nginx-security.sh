#!/bin/sh
set -eu

PROJECT_ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
TEST_DIR=$(mktemp -d)
TEST_NETWORK="expense-nginx-security-$$"
BACKEND_CONTAINER="expense-nginx-backend-$$"
NGINX_CONTAINER="expense-nginx-proxy-$$"

cleanup() {
    docker rm -f "$NGINX_CONTAINER" "$BACKEND_CONTAINER" >/dev/null 2>&1 || true
    docker network rm "$TEST_NETWORK" >/dev/null 2>&1 || true
    rm -rf "$TEST_DIR"
}
trap cleanup EXIT INT TERM

mkdir -p "$TEST_DIR/certs" "$TEST_DIR/www"
printf 'healthy\n' >"$TEST_DIR/www/health"
printf 'must not reach the app\n' >"$TEST_DIR/www/wp-login.php"

openssl req -x509 -newkey rsa:2048 -nodes -days 1 \
    -subj "/CN=alessandra8566.com" \
    -keyout "$TEST_DIR/certs/privkey.pem" \
    -out "$TEST_DIR/certs/fullchain.pem" >/dev/null 2>&1

docker network create "$TEST_NETWORK" >/dev/null
docker run -d --name "$BACKEND_CONTAINER" --network "$TEST_NETWORK" \
    --network-alias app \
    -v "$TEST_DIR/www:/srv:ro" \
    python:3.12-slim python -m http.server 8000 --directory /srv >/dev/null

docker run -d --name "$NGINX_CONTAINER" --network "$TEST_NETWORK" \
    -p 127.0.0.1::80 -p 127.0.0.1::443 \
    -v "$PROJECT_ROOT/nginx/nginx.conf:/etc/nginx/conf.d/default.conf:ro" \
    -v "$TEST_DIR/certs:/etc/letsencrypt/live/alessandra8566.com:ro" \
    nginx:alpine >/dev/null

HTTP_PORT=$(docker inspect --format '{{(index (index .NetworkSettings.Ports "80/tcp") 0).HostPort}}' "$NGINX_CONTAINER")
HTTPS_PORT=$(docker inspect --format '{{(index (index .NetworkSettings.Ports "443/tcp") 0).HostPort}}' "$NGINX_CONTAINER")

attempt=0
while ! curl -fsS -o /dev/null \
    --noproxy '*' \
    -H 'Host: alessandra8566.com' \
    "http://127.0.0.1:$HTTP_PORT/health"; do
    attempt=$((attempt + 1))
    if [ "$attempt" -ge 20 ]; then
        echo "nginx did not become ready" >&2
        docker logs "$NGINX_CONTAINER" >&2
        exit 1
    fi
    sleep 0.1
done

assert_status() {
    expected=$1
    shift
    actual=$(curl --noproxy '*' -ksS -o /dev/null -w '%{http_code}' "$@" || true)
    if [ "$actual" != "$expected" ]; then
        echo "expected HTTP $expected, got $actual: curl $*" >&2
        exit 1
    fi
}

# Unknown hosts and direct-IP traffic must be dropped before reaching the app.
assert_status 000 -H 'Host: 188.166.226.40' "http://127.0.0.1:$HTTP_PORT/"
assert_status 000 --resolve "scanner.invalid:$HTTPS_PORT:127.0.0.1" \
    "https://scanner.invalid:$HTTPS_PORT/"

# Only the two public application endpoints may reach FastAPI.
assert_status 200 --resolve "alessandra8566.com:$HTTPS_PORT:127.0.0.1" \
    "https://alessandra8566.com:$HTTPS_PORT/health"
assert_status 404 --resolve "alessandra8566.com:$HTTPS_PORT:127.0.0.1" \
    "https://alessandra8566.com:$HTTPS_PORT/wp-login.php"

mkdir -p "$TEST_DIR/rate-statuses"
request_number=1
while [ "$request_number" -le 30 ]; do
    (
        curl --noproxy '*' -ksS -o /dev/null -w '%{http_code}' \
            --resolve "alessandra8566.com:$HTTPS_PORT:127.0.0.1" \
            "https://alessandra8566.com:$HTTPS_PORT/health" \
            >"$TEST_DIR/rate-statuses/$request_number"
    ) &
    request_number=$((request_number + 1))
done
wait

if ! grep -q '^503$' "$TEST_DIR"/rate-statuses/*; then
    echo "expected a burst request to be rate-limited with HTTP 503" >&2
    exit 1
fi

echo "nginx security routing checks passed"
