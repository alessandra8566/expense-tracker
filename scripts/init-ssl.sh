#!/bin/bash
# =============================================================================
# init-ssl.sh — Run ONCE on the server to obtain the first SSL certificate.
#
# What this script does:
#   1. Starts nginx with HTTP-only bootstrap config (so certbot can respond to
#      the ACME challenge on port 80 without needing certs yet)
#   2. Runs certbot to obtain the real Let's Encrypt certificate
#   3. Swaps nginx to the full HTTPS config and reloads
#   4. Starts the certbot auto-renewal container
#
# Usage (on the server, inside ~/expense-tracker):
#   chmod +x scripts/init-ssl.sh
#   ./scripts/init-ssl.sh your@email.com
# =============================================================================

set -euo pipefail

DOMAIN="alessandra8566.com"
EMAIL="${1:-}"
COMPOSE_FILE="docker-compose.prod.yml"

# ── Validate ──────────────────────────────────────────────────────────────────
if [[ -z "$EMAIL" ]]; then
  echo "❌  Usage: $0 your@email.com"
  exit 1
fi

if [[ ! -f ".env.prod" ]]; then
  echo "❌  .env.prod not found. Create it from .env.example first."
  exit 1
fi

echo ""
echo "🚀  Starting SSL initialisation for ${DOMAIN}"
echo "────────────────────────────────────────────────"

# ── Step 1: Start db + app first ──────────────────────────────────────────────
echo "▶  Step 1: Starting database and app..."
docker compose -f "$COMPOSE_FILE" up -d db app
echo "   Waiting 10s for DB to become healthy..."
sleep 10

# ── Step 2: Start nginx with bootstrap (HTTP-only) config ────────────────────
echo "▶  Step 2: Starting nginx in HTTP-only mode..."
docker run -d \
  --name tmp_nginx_bootstrap \
  --network expense-tracker_internal \
  -p 80:80 \
  -v "$(pwd)/nginx/nginx.bootstrap.conf:/etc/nginx/conf.d/default.conf:ro" \
  -v "certbot_www:/var/www/certbot" \
  nginx:alpine

echo "   Waiting 3s for nginx to start..."
sleep 3

# ── Step 3: Obtain certificate via certbot ────────────────────────────────────
echo "▶  Step 3: Obtaining Let's Encrypt certificate..."
docker run --rm \
  --network expense-tracker_internal \
  -v "/etc/letsencrypt:/etc/letsencrypt" \
  -v "certbot_www:/var/www/certbot" \
  certbot/certbot certonly \
    --webroot \
    --webroot-path=/var/www/certbot \
    -d "${DOMAIN}" \
    -d "www.${DOMAIN}" \
    --email "${EMAIL}" \
    --agree-tos \
    --no-eff-email \
    --non-interactive

# ── Step 4: Stop bootstrap nginx ─────────────────────────────────────────────
echo "▶  Step 4: Stopping bootstrap nginx..."
docker stop tmp_nginx_bootstrap && docker rm tmp_nginx_bootstrap

# ── Step 5: Start full production stack (HTTPS nginx + certbot renewal) ───────
echo "▶  Step 5: Starting full production stack with HTTPS..."
docker compose -f "$COMPOSE_FILE" up -d

echo ""
echo "✅  Done! SSL certificate obtained and nginx is running with HTTPS."
echo ""
echo "   🌐  https://${DOMAIN}/health    ← verify it works"
echo "   🔗  Set LINE Webhook URL:  https://${DOMAIN}/webhook"
echo ""
echo "   Certbot will automatically renew the cert every 12 hours (renews when <30 days left)."
