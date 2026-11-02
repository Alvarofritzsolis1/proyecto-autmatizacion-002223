#!/usr/bin/env bash
# Ensayo seguro y aislado GALANT 2.0. No toca /opt/galant, 80/443, DNS, SSH ni firewall.
set -Eeuo pipefail
umask 077
cd "$(dirname "${BASH_SOURCE[0]}")/.."

if [[ "$(id -u)" -ne 0 ]]; then
  echo "Ejecuta: sudo bash scripts/preview-install.sh" >&2
  exit 1
fi
if ! grep -qi '^ID=ubuntu' /etc/os-release || ! grep -Eq '^VERSION_ID="?24[.]04"?' /etc/os-release; then
  echo "Solo compatible con Ubuntu 24.04 LTS." >&2
  exit 1
fi
for command_name in docker openssl ss curl awk df grep; do
  if ! command -v "$command_name" >/dev/null 2>&1; then
    echo "Falta $command_name. No se instalarán paquetes ni se alterará el VPS." >&2
    exit 1
  fi
done
if ! docker compose version >/dev/null 2>&1; then
  echo "Se requiere Docker Compose V2." >&2
  exit 1
fi
if [[ -f .env.preview ]] && [[ ! -s .env.preview ]]; then
  echo ".env.preview existe pero está vacío. Revisar sin eliminarlo." >&2
  exit 1
fi
available_mb=$(awk '/MemAvailable:/ {print int($2/1024)}' /proc/meminfo)
disk_mb=$(df -Pm . | awk 'NR==2 {print $4}')
echo "Recursos disponibles: RAM ${available_mb} MB; disco ${disk_mb} MB."
# Conservar holgura para GALANT antiguo, sistema y compilación de Docker.
if ((available_mb < 2500 || disk_mb < 5500)); then
  echo "Recursos libres insuficientes para mantener ambas versiones a la vez. No se ha cambiado nada." >&2
  exit 1
fi
if [[ "$(readlink -f .)" != "/opt/galant2-preview" ]]; then
  echo "Por seguridad la carpeta esperada es /opt/galant2-preview." >&2
  echo "Copia/clona esta rama allí antes de instalar." >&2
  exit 1
fi
running_proxy=$(docker compose --env-file .env.preview -f docker-compose.preview.yml ps -q proxy 2>/dev/null || true)
if ss -lntH 'sport = :18502' | grep -q . && [[ -z "$running_proxy" ]]; then
  echo "El puerto 18502 está en uso por otro proceso. No se modificará." >&2
  exit 1
fi
if [[ ! -f .env.preview ]]; then
  secret=$(openssl rand -hex 48)
  password=$(openssl rand -hex 24)
  printf 'APP_SECRET=%s\nPOSTGRES_PASSWORD=%s\nOCR_LANG=spa+eng\n' "$secret" "$password" > .env.preview
  chmod 600 .env.preview
fi
if ! grep -Eq '^APP_SECRET=[[:xdigit:]]{64,}$' .env.preview || ! grep -Eq '^POSTGRES_PASSWORD=[[:xdigit:]]{32,}$' .env.preview; then
  echo "Credenciales de prueba inválidas; se conserva .env.preview para revisión." >&2
  exit 1
fi
install -d -m 0700 preview-storage
chown 10001:10001 preview-storage
chmod 0700 preview-storage

# Proyecto y volúmenes independientes: galant2-preview, no galant/galant2.
compose=(docker compose --env-file .env.preview -f docker-compose.preview.yml)
"${compose[@]}" config --quiet
echo "Compilando y levantando únicamente GALANT 2.0 PREVIEW. Esta operación puede consumir CPU/disco."
COMPOSE_PARALLEL_LIMIT=1 "${compose[@]}" build
"${compose[@]}" up -d db api worker frontend proxy
"${compose[@]}" exec -T api alembic upgrade head

success=0
for _ in {1..35}; do
  if curl -fsS --max-time 5 http://127.0.0.1:18502/api/v1/health | grep -q '"status":"ok"'; then
    success=1
    break
  fi
  sleep 3
done
if ((success != 1)); then
  echo "La API no pasó el chequeo local. Diagnóstico:" >&2
  "${compose[@]}" ps >&2
  "${compose[@]}" logs --tail=40 api db proxy >&2
  exit 1
fi
echo
echo "Ensayo activo SOLO en el VPS, http://127.0.0.1:18502"
echo "Siguiente: crear administrador (contraseña interactiva, NO enviar al chat):"
echo '  sudo docker compose --env-file .env.preview -f docker-compose.preview.yml exec api python -m app.cli create-admin --email TU-CORREO@EMPRESA.CL'
echo "DESDE POWERSHELL EN TU PC, NO dentro del VPS:"
echo "  ssh -N -L 18502:127.0.0.1:18502 root@89.117.144.140"
echo "Luego abre en tu PC http://127.0.0.1:18502"
echo "Usar SOLO archivos sintéticos. No subir documentación laboral real."
