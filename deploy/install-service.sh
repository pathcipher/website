#!/usr/bin/env bash
#
# Install a systemd service that brings the production Docker Compose stack up
# on boot and stops it cleanly on shutdown.
#
# The unit file is generated here (rather than shipped static) so the absolute
# paths — project directory and Docker Compose command — are correct for this
# machine.
#
# Usage (as root):
#   sudo ./deploy/install-service.sh
#   sudo SERVICE_NAME=pathcipher ./deploy/install-service.sh   # custom name
#
set -euo pipefail

SERVICE_NAME="${SERVICE_NAME:-pathcipher}"

if [ "$(id -u)" -ne 0 ]; then
  echo "ERROR: run as root (installing a systemd unit needs it):" >&2
  echo "       sudo $0" >&2
  exit 1
fi

# Repo root = the parent of this script's directory.
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
COMPOSE_FILE="$PROJECT_DIR/docker-compose.prod.yml"

if [ ! -f "$COMPOSE_FILE" ]; then
  echo "ERROR: $COMPOSE_FILE not found." >&2
  exit 1
fi
if [ ! -f "$PROJECT_DIR/.env" ]; then
  echo "WARNING: $PROJECT_DIR/.env not found — the stack needs it at runtime." >&2
fi

# Pick a Compose command with an absolute path (systemd needs absolute paths).
DOCKER_BIN="$(command -v docker || true)"
if [ -n "$DOCKER_BIN" ] && "$DOCKER_BIN" compose version >/dev/null 2>&1; then
  COMPOSE="$DOCKER_BIN compose"
elif command -v docker-compose >/dev/null 2>&1; then
  COMPOSE="$(command -v docker-compose)"
else
  echo "ERROR: no Docker Compose found (need 'docker compose' v2 or docker-compose)." >&2
  echo "       sudo apt-get install docker-compose-plugin" >&2
  exit 1
fi

UNIT_PATH="/etc/systemd/system/${SERVICE_NAME}.service"

cat > "$UNIT_PATH" <<UNIT
[Unit]
Description=Pathcipher production stack (Docker Compose)
Requires=docker.service
After=docker.service network-online.target
Wants=network-online.target

[Service]
Type=oneshot
RemainAfterExit=yes
WorkingDirectory=${PROJECT_DIR}
ExecStart=${COMPOSE} -f ${COMPOSE_FILE} up -d --remove-orphans
ExecStop=${COMPOSE} -f ${COMPOSE_FILE} down
ExecReload=${COMPOSE} -f ${COMPOSE_FILE} up -d --remove-orphans
TimeoutStartSec=0

[Install]
WantedBy=multi-user.target
UNIT

echo "Wrote ${UNIT_PATH}:"
echo "------------------------------------------------------------"
cat "$UNIT_PATH"
echo "------------------------------------------------------------"

systemctl daemon-reload
systemctl enable "${SERVICE_NAME}.service"

cat <<INFO

Installed and enabled '${SERVICE_NAME}'. It will start on every boot.

Manage it with:
  sudo systemctl start ${SERVICE_NAME}     # bring the stack up now
  sudo systemctl stop ${SERVICE_NAME}      # stop the stack (compose down)
  sudo systemctl status ${SERVICE_NAME}
  journalctl -u ${SERVICE_NAME}            # view logs

Note: the unit runs 'up -d' (no build) so boot is fast and offline-safe.
To deploy new code, rebuild then restart:
  cd ${PROJECT_DIR} && git pull
  ${COMPOSE} -f ${COMPOSE_FILE} up -d --build
INFO
