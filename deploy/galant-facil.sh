#!/usr/bin/env bash
# Instalador asistido de GALANT (Ubuntu VPS Contabo).
# Ejecutar como usuario administrativo con: bash deploy/galant-facil.sh
set -Eeuo pipefail

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$DIR"
DOMINIO="galant.dpdns.org"
IP_VPS="89.117.144.140"
COMPOSE=(sudo docker compose)
PRIVADO=(-f compose.yaml -f deploy/compose.private.yaml)

die() { printf "\nERROR: %s\n" "$*" >&2; exit 1; }
info() { printf "\n== %s ==\n" "$*"; }
require_docker() {
  command -v docker >/dev/null || die "Docker no instalado. Instala Docker Engine + Compose antes."
  "${COMPOSE[@]}" version >/dev/null || die "Docker Compose no disponible. Revisa permisos o instalacion de Docker."
}
ensure_env() {
  if [[ ! -f .env ]]; then
    printf "GALANT_DOMAIN=%s\nGALANT_USER=auditor\n" "$DOMINIO" > .env
    chmod 600 .env
    printf "Archivo .env minimo creado para modo privado. Aun falta configurar la clave de produccion.\n"
  fi
  # La variable GALANT_DOMAIN debe estar definida aunque Caddy no arranque.
  if ! grep -Eq '^GALANT_DOMAIN=.+$' .env; then
    printf '\nGALANT_DOMAIN=%s\n' "$DOMINIO" >> .env
  fi
  chmod 600 .env
}
dns_ipv4() {
  if command -v dig >/dev/null; then
    dig +time=4 +tries=1 +short @1.1.1.1 "$DOMINIO" A | grep -E '^[0-9]+(\.[0-9]+){3}$' || true
  elif command -v nslookup >/dev/null; then
    nslookup "$DOMINIO" 1.1.1.1 | awk '/^Non-authoritative answer:/ {ready=1;next} ready && /^Address:/ {print $2}' || true
  else
    printf "(instala dnsutils para consulta de DNS)\n"
  fi
}
show_dns() {
  info "Destino DNS publico"
  printf "%s debe apuntar a %s\n" "$DOMINIO" "$IP_VPS"
  actual="$(dns_ipv4)"
  printf "Respuesta actual: %s\n" "${actual:-sin respuesta}"
  if [[ "$actual" == "$IP_VPS" ]]; then
    printf "OK: registro A coincide.\n"
  else
    printf "AUN NO: revisa el registro A en el DNS autoritativo de DigitalPlat.\n"
    printf "No es posible corregir el DNS publico desde esta terminal sin acceso a tu proveedor DNS.\n"
  fi
  printf "\nPara comparar DNS autoritativo, si tienes dig:\n"
  printf "dig +trace %s A\n" "$DOMINIO"
}
private_mode() {
  require_docker
  ensure_env
  info "Validando Compose privado"
  "${COMPOSE[@]}" "${PRIVADO[@]}" config --quiet
  info "Construyendo/activando GALANT SOLO en 127.0.0.1:18501"
  "${COMPOSE[@]}" "${PRIVADO[@]}" up -d --build --wait --wait-timeout 180 galant
  "${COMPOSE[@]}" "${PRIVADO[@]}" ps galant
  printf '\nGALANT PRUEBA PRIVADA: En TU PC con Windows abre PowerShell y escribe:\n'
  printf 'ssh -L 18501:127.0.0.1:18501 root@%s\n' "$IP_VPS"
  printf 'Manten esa ventana abierta y visita http://localhost:18501\n'
  printf 'Este modo no publica 8501 ni necesita DNS/HTTPS publico.\n'
  printf 'NO cargues documentos laborales reales hasta establecer el acceso de produccion.\n'
}
produce() {
  require_docker
  ensure_env
  info "Comprobando dominio"
  actual="$(dns_ipv4)"
  if [[ "$actual" != "$IP_VPS" ]]; then
    show_dns
    die "El dominio aun no apunta exclusivamente a Contabo. NO se inicia HTTPS."
  fi
  if ! grep -q '^GALANT_AUTH_HASH=' .env || grep -q 'REEMPLAZAR\|AQUI_VA\|TU_HASH' .env; then
    die "Falta configurar GALANT_AUTH_HASH (hash real de Caddy) en .env. No solicito contrasenas por chat."
  fi
  info "Validando configuracion"
  "${COMPOSE[@]}" config --quiet
  info "Activando GALANT y Caddy HTTPS"
  "${COMPOSE[@]}" up -d --build --wait --wait-timeout 180 galant caddy
  "${COMPOSE[@]}" ps
  printf '\nComprueba el acceso protegido en https://%s\n' "$DOMINIO"
  printf 'Caddy emitira el certificado si los puertos 80/443 estan accesibles desde Internet.\n'
}
status() {
  require_docker
  ensure_env
  "${COMPOSE[@]}" "${PRIVADO[@]}" ps || true
  show_dns
}
printf '\nGALANT - Instalacion facil en Contabo\n'
printf '1) Probar GALANT en privado (no requiere dominio)\n'
printf '2) Publicar GALANT en HTTPS (requiere DNS correcto y hash)\n'
printf '3) Comprobar DNS\n'
printf '4) Estado de GALANT\n'
printf 'Opcion [1-4]: '
read -r opcion
case "$opcion" in
  1) private_mode ;;
  2) produce ;;
  3) show_dns ;;
  4) status ;;
  *) die "Elige 1, 2, 3 o 4" ;;
esac
