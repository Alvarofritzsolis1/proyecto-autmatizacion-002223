#!/usr/bin/env bash
set -Eeuo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"
echo 'Realiza backup verificado antes de actualizar. Revisa cambios en GitHub.'
git pull --ff-only
docker compose config --quiet
docker compose build
docker compose up -d db api worker frontend proxy
docker compose exec -T api alembic upgrade head
docker compose ps
