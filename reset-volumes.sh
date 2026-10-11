#!/usr/bin/env bash
# Destroy all Docker Compose volumes and recreate from scratch.
# WARNING: All persisted data (postgres, redis, minio, kafka, neo4j, etc.) will be lost.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
# The development stack's host mounts (docker-compose.e2e-mounts.yml; #201). The overlay has no
# defaults, so they are named here: directories of THIS checkout, which the e2e specs write
# under and Trino must see at the same absolute path.
export PROVISA_E2E_FILE_LAKE_HOST="${PROVISA_E2E_FILE_LAKE_HOST:-$SCRIPT_DIR/.e2e-file-lake}"
export PROVISA_E2E_HIVE_WAREHOUSE_HOST="${PROVISA_E2E_HIVE_WAREHOUSE_HOST:-$SCRIPT_DIR/.e2e-hive-warehouse}"
export PROVISA_E2E_SHAREPOINT_CERT_HOST="${PROVISA_E2E_SHAREPOINT_CERT_HOST:-$SCRIPT_DIR/sharepoint.pfx}"
COMPOSE_FILES="-f docker-compose.core.yml -f docker-compose.dev.yml -f docker-compose.e2e-mounts.yml"

echo "WARNING: This will destroy ALL data volumes. This cannot be undone."
echo "Press Ctrl+C within 5 seconds to abort..."
for i in 5 4 3 2 1; do printf "\r  %s..." "$i"; sleep 1; done
echo ""

cd "$SCRIPT_DIR"
docker compose $COMPOSE_FILES down --remove-orphans
docker compose $COMPOSE_FILES down -v --remove-orphans
echo "Volumes removed. Run start-ui.sh to reinitialize."
