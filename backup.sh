#!/usr/bin/env bash
set -Eeuo pipefail
umask 077
cd "$(dirname "${BASH_SOURCE[0]}")"
[[ -f .env ]] || { echo 'Falta archivo .env' >&2; exit 1; }
set -a; source .env; set +a
[[ -n "${BACKUP_GPG_RECIPIENT:-}" ]] || { echo 'Configura BACKUP_GPG_RECIPIENT y su clave pública' >&2; exit 1; }
command -v gpg >/dev/null || { echo 'GPG no instalado' >&2; exit 1; }
mkdir -p backups; chmod 700 backups
STAMP=$(date -u +%Y%m%dT%H%M%SZ)
DATABASE_OUT="backups/galant-db-${STAMP}.dump.gpg"
DOCUMENTS_OUT="backups/galant-files-${STAMP}.tar.gpg"
docker compose exec -T db pg_dump -U galant -d galant --no-owner --format=custom \
  | gpg --batch --yes --trust-model always --encrypt -r "$BACKUP_GPG_RECIPIENT" -o "$DATABASE_OUT"
tar -cf - -C . storage \
  | gpg --batch --yes --trust-model always --encrypt -r "$BACKUP_GPG_RECIPIENT" -o "$DOCUMENTS_OUT"
chmod 600 "$DATABASE_OUT" "$DOCUMENTS_OUT"
echo "Backup cifrado: $DATABASE_OUT y $DOCUMENTS_OUT"
echo 'Verifica restauración en un entorno aislado antes de depender de este respaldo.'
