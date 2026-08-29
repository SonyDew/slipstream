#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# Update a running Slipstream instance.
#
#   docker/update.sh                     # base compose file
#   docker/update.sh -f docker-compose.ubuntu.yml
#
# Takes a backup first, then rebuilds and restarts. Extra arguments are passed
# through to `docker compose`, so overlay files work as usual.
# ---------------------------------------------------------------------------
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

COMPOSE_ARGS=(-f docker-compose.yml "$@")
CONTAINER="${CONTAINER:-slipstream}"

echo "==> backing up before the update"
if docker inspect "$CONTAINER" >/dev/null 2>&1; then
  docker/backup.sh
else
  echo "    (no running container; skipping)"
fi

echo "==> rebuilding the image"
# --pull refreshes the base images too, which is where OS-level security fixes
# and a newer ffmpeg arrive.
docker compose "${COMPOSE_ARGS[@]}" build --pull

echo "==> restarting"
docker compose "${COMPOSE_ARGS[@]}" up -d --remove-orphans

echo "==> waiting for health"
for _ in $(seq 1 45); do
  if docker exec "$CONTAINER" curl -fsS http://127.0.0.1:8000/api/health/ready >/dev/null 2>&1; then
    echo "==> healthy"
    docker compose "${COMPOSE_ARGS[@]}" exec -T app python -m app.cli verify || true
    echo
    echo "==> old images left in place. Reclaim space with: docker image prune -f"
    exit 0
  fi
  sleep 2
done

echo "WARNING: not ready after 90s." >&2
echo "Logs:    docker compose ${COMPOSE_ARGS[*]} logs --tail=50 app" >&2
echo "Rollback: docker/restore.sh backups/<latest>.tar.gz" >&2
exit 1
