#!/usr/bin/env bash
set -Eeuo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"
if [[ "${1:-}" != "--confirm-restore" || $# -ne 3 ]]; then
  echo 'Uso destructivo: ./restore.sh --confirm-restore BD.dump.gpg DOCUMENTOS.tar.gpg' >&2
  exit 1
fi
DB_BACKUP=$2
FILES_BACKUP=$3
[[ -f "$DB_BACKUP" && -f "$FILES_BACKUP" ]] || { echo 'Respaldo no encontrado' >&2; exit 1; }
[[ -f .env ]] || { echo 'Falta .env' >&2; exit 1; }
echo 'ADVERTENCIA: Reemplazará datos actuales.'
read -r -p 'Escribe RESTAURAR para continuar: ' CONFIRM
[[ "$CONFIRM" == 'RESTAURAR' ]] || exit 1
docker compose stop api worker
docker compose up -d db
gpg --batch --decrypt "$DB_BACKUP" | docker compose exec -T db pg_restore -U galant -d galant --clean --if-exists --no-owner
mkdir -p storage
gpg --batch --decrypt "$FILES_BACKUP" | tar -xf - -C . --no-same-owner
chown -R 10001:100 storage
chmod 700 storage
docker compose up -d api worker frontend proxy
docker compose exec -T api python -c 'import urllib.request;urllib.request.urlopen("http://127.0.0.1:8000/api/v1/health",timeout=6)'
echo 'Restauración ejecutada: verificar documentos, permisos y sesiones.'
