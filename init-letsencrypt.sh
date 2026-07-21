#!/usr/bin/env bash
#
# One-time Let's Encrypt bootstrap for the production stack.
#
# Prerequisites:
#   * DNS A/AAAA records for $DOMAIN (and www.$DOMAIN) point at this VPS
#   * .env filled in (DOMAIN, CERTBOT_EMAIL, DJANGO_SECRET_KEY, POSTGRES_*)
#   * ports 80/443 open
#
# Usage:
#   ./init-letsencrypt.sh            # real certificate
#   STAGING=1 ./init-letsencrypt.sh  # Let's Encrypt staging (for testing)
#
set -euo pipefail

# --- Preflight: is the Docker daemon reachable? ---
if ! docker info >/dev/null 2>&1; then
  echo "ERROR: cannot talk to the Docker daemon." >&2
  echo "  * Start it:      sudo systemctl start docker  (then: sudo systemctl enable docker)" >&2
  echo "  * Permissions:   sudo usermod -aG docker \"\$USER\"  then log out/in (or: newgrp docker)" >&2
  echo "  * Verify:        docker info" >&2
  exit 1
fi

# --- Pick a Compose command: prefer v2 ('docker compose'), fall back to v1. ---
if docker compose version >/dev/null 2>&1; then
  COMPOSE="docker compose -f docker-compose.prod.yml"
elif command -v docker-compose >/dev/null 2>&1; then
  echo "NOTE: using legacy docker-compose v1. Compose v2 is recommended:" >&2
  echo "      sudo apt-get install docker-compose-plugin   (then use 'docker compose')" >&2
  COMPOSE="docker-compose -f docker-compose.prod.yml"
else
  echo "ERROR: no Docker Compose found. Install the plugin:" >&2
  echo "       sudo apt-get install docker-compose-plugin" >&2
  exit 1
fi

if [ ! -f .env ]; then
  echo "ERROR: .env not found. Copy .env.example to .env and fill it in." >&2
  exit 1
fi
set -a; . ./.env; set +a

: "${DOMAIN:?Set DOMAIN in .env}"
: "${CERTBOT_EMAIL:?Set CERTBOT_EMAIL in .env}"

domains=("$DOMAIN" "www.$DOMAIN")
rsa_key_size=4096
staging="${STAGING:-0}"
live_path="/etc/letsencrypt/live/$DOMAIN"

echo "### Creating a temporary self-signed certificate so nginx can start ..."
$COMPOSE run --rm --entrypoint "\
  sh -c 'mkdir -p $live_path && \
    openssl req -x509 -nodes -newkey rsa:$rsa_key_size -days 1 \
      -keyout $live_path/privkey.pem \
      -out $live_path/fullchain.pem \
      -subj \"/CN=$DOMAIN\"'" certbot

echo "### Building and starting the stack ..."
$COMPOSE up -d --build

echo "### Removing the temporary certificate ..."
$COMPOSE run --rm --entrypoint "\
  rm -rf /etc/letsencrypt/live/$DOMAIN \
         /etc/letsencrypt/archive/$DOMAIN \
         /etc/letsencrypt/renewal/$DOMAIN.conf" certbot

echo "### Requesting the real Let's Encrypt certificate ..."
domain_args=()
for d in "${domains[@]}"; do domain_args+=(-d "$d"); done
staging_arg=""
[ "$staging" != "0" ] && staging_arg="--staging"

$COMPOSE run --rm --entrypoint "\
  certbot certonly --webroot -w /var/www/certbot $staging_arg \
    --email $CERTBOT_EMAIL ${domain_args[*]} \
    --rsa-key-size $rsa_key_size --agree-tos --no-eff-email --force-renewal" certbot

echo "### Reloading nginx with the new certificate ..."
$COMPOSE exec nginx nginx -s reload

echo
echo "### Done. https://$DOMAIN should now be live."
