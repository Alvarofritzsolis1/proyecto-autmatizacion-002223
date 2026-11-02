#!/usr/bin/env bash
set -Eeuo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."
printf '\n=== Docker Compose ===\n'
docker compose ps
printf '\n=== Logs de servicios ===\n'
docker compose logs --tail=35 api worker proxy
printf '\n=== Puertos del sistema ===\n'
ss -lntp | grep -E ':(80|443|22) ' || true
