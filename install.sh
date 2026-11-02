#!/usr/bin/env bash
set -Eeuo pipefail
umask 077
cd "$(dirname "${BASH_SOURCE[0]}")"
if [[ "$(id -u)" -ne 0 ]]; then echo 'Ejecutar con sudo.' >&2; exit 1; fi
if ! grep -qi '^ID=ubuntu' /etc/os-release || ! grep -q 'VERSION_ID="24.04"' /etc/os-release; then
  echo 'Instalador diseñado únicamente para Ubuntu 24.04 LTS.' >&2; exit 1
fi
RAM_MB=$(awk '/MemTotal/ {printf "%.0f",$2/1024}' /proc/meminfo)
DISK_MB=$(df -Pm . | awk 'NR==2{print $4}')
CPU=$(nproc)
echo "Recursos: ${CPU} CPU, ${RAM_MB} MB RAM, ${DISK_MB} MB disco libre."
if (( RAM_MB<1800 || DISK_MB<4500 )); then echo 'Recursos insuficientes para el perfil inicial.' >&2; exit 1; fi
if ! command -v docker >/dev/null 2>&1; then
  if [[ "${1:-}" != "--install-docker" ]]; then echo 'Docker ausente; reejecuta con --install-docker' >&2; exit 1; fi
  apt-get update
  DEBIAN_FRONTEND=noninteractive apt-get install -y docker.io docker-compose-v2
  systemctl enable --now docker
fi
if ! docker compose version >/dev/null 2>&1; then echo 'Falta docker compose v2' >&2; exit 1; fi
for port in 80 443; do
  if command -v ss >/dev/null && ss -lntH "sport = :$port" | grep -q . && ! docker compose ps -q proxy 2>/dev/null | grep -q .; then
    echo "Puerto ${port} ocupado. No modificaremos otro servicio." >&2; exit 1
  fi
done
if [[ ! -f .env ]]; then
  command -v openssl >/dev/null || { echo 'OpenSSL requerido' >&2; exit 1; }
  secret=$(openssl rand -hex 48);password=$(openssl rand -hex 24)
  sed -e "s/APP_SECRET=REEMPLAZAR_POR_SECRETO_SEGURO/APP_SECRET=${secret}/" \
      -e "s/POSTGRES_PASSWORD=REEMPLAZAR_POR_PASSWORD_SEGURO/POSTGRES_PASSWORD=${password}/" \
      .env.example >.env
  chmod 600 .env
fi
if grep -q REEMPLAZAR_POR_ .env;then echo 'Credenciales de ejemplo no permitidas' >&2;exit 1;fi
if grep -q '^GALANT_SITE=:80' .env;then
  echo 'MODO DE PRUEBA: HTTP sin TLS. No cargar datos laborales reales.'
elif ! grep -q '^COOKIE_SECURE=true' .env;then
  echo 'El acceso HTTPS requiere COOKIE_SECURE=true' >&2;exit 1
fi
mkdir -p storage backups
chown -R 10001:100 storage
chmod 700 storage backups
docker compose config --quiet
docker compose build
docker compose up -d db api worker frontend proxy
docker compose exec -T api alembic upgrade head
attempt=0
until docker compose exec -T api python -c 'import urllib.request;urllib.request.urlopen("http://127.0.0.1:8000/api/v1/health",timeout=4)' >/dev/null 2>&1;do
  attempt=$((attempt+1))
  if ((attempt>=25));then echo 'Falla de salud API. Ver docker compose logs api db' >&2;exit 1;fi
  sleep 3
done
echo 'API activa. Verificar HTTPS, migraciones y restauración antes de uso real.'
echo 'Crear admin: docker compose exec api python -m app.cli create-admin --email TU@EMPRESA.CL'
