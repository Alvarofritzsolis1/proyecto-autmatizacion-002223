# GALANT 2.0 — Despliegue de prueba sin afectar al sistema anterior

**Objetivo:** desplegar la rama de reconstrucción en un proyecto Docker independiente, accesible únicamente mediante un túnel SSH. No requiere modificar el dominio, puertos 80/443, firewall ni la carpeta del GALANT anterior.

> **NO PRODUCCIÓN / SIN DOCUMENTOS LABORALES REALES.** La interfaz funciona por HTTP local transportado por SSH, sin HTTPS público. Las pruebas sintéticas de CI no equivalen a validación de precisión sobre Previred/F30-1 reales.

## 1. En el VPS Ubuntu 24.04 (terminal donde aparece root@...)

Comprueba primero que Docker/Compose y Git estén instalados:

```bash
docker --version
docker compose version
git --version
```

Si Git falta, instala únicamente Git con el gestor de paquetes del sistema (no afecta al sitio previo). Luego:

```bash
sudo git clone --branch refactor/galant-2-react-fastapi-20261102 --single-branch \
  https://github.com/Alvarofritzsolis1/proyecto-autmatizacion-002223.git \
  /opt/galant2-preview
cd /opt/galant2-preview
sudo bash scripts/preview-install.sh
```

El instalador:
- verifica Ubuntu, Docker, puertos, espacio y al menos 2500 MB de RAM disponible; **se niega a instalar** si no hay holgura para la aplicación anterior;
- crea secretos privados en `.env.preview` (nunca los compartas);
- ejecuta **solo** `docker-compose.preview.yml`, proyecto `galant2-preview`;
- crea base de datos y archivos separados en `preview_postgres_data` y `preview-storage/`;
- publica **únicamente** `127.0.0.1:18502` del VPS, no el puerto público 80/443;
- construye imágenes, aplica migración y verifica `/api/v1/health`.

El script no hace `docker compose down` del proyecto anterior, no ejecuta comandos sobre `/opt/galant`, no instala Docker automáticamente y no modifica el DNS ni SSH.

Si el instalador informa RAM insuficiente, **no detengas el sistema anterior** para forzar la prueba. Es necesario revisar los recursos disponibles y elegir un plan de ejecución alternativo.

## 2. Crear usuario de prueba en el VPS

Dentro de `/opt/galant2-preview`:

```bash
sudo docker compose --env-file .env.preview -f docker-compose.preview.yml \
  exec api python -m app.cli create-admin --email TU-CORREO@EMPRESA.CL
```

Elige una contraseña propia cuando se solicite en consola. No la escribas en este chat.

## 3. Desde Windows: PowerShell NUEVO en tu computador

**No ejecutes SSH -L dentro de root@vmi3719391.** En tu computadora Windows, abre PowerShell y ejecuta:

```powershell
ssh -N -L 18502:127.0.0.1:18502 root@89.117.144.140
```

Mantén abierta esa ventana mientras pruebas. En el navegador del **mismo PC** visita:

`http://127.0.0.1:18502`

Inicia sesión con el usuario creado. Prueba con documentos ficticios/sintéticos.

## 4. Diagnóstico

En el VPS:

```bash
cd /opt/galant2-preview
sudo docker compose --env-file .env.preview -f docker-compose.preview.yml ps
sudo docker compose --env-file .env.preview -f docker-compose.preview.yml logs --tail=50 api worker proxy
curl --fail --silent --show-error http://127.0.0.1:18502/api/v1/health
sudo ss -lntp | grep 18502
```

**Si el puerto 18502 ya está ocupado**, el instalador se detiene sin modificar el otro proceso. No remplaces arbitrariamente los puertos de producción.

**Si Docker informa falta de RAM/disco**, no uses `docker system prune -a` ni elimines volúmenes: podrías perder datos del sistema anterior.

## 5. Detener únicamente la prueba

```bash
cd /opt/galant2-preview
sudo docker compose --env-file .env.preview -f docker-compose.preview.yml stop
```

Esto detiene solo los contenedores de GALANT 2.0 Preview. **No usar `down -v`**: borraría la base de datos de prueba.

## 6. Criterios antes del dominio real

- Página React visible por túnel y login autorizado.
- API y worker estables tras reiniciar los contenedores de prueba.
- PDF sintético digital, escaneado y mixto: evidencia trazable, sin afirmar verificación externa.
- Memoria y carga de CPU del VPS suficientes para no degradar la aplicación anterior.
- Benchmark privado representativo Previred/F30-1, endurecimiento de seguridad y respaldo/restauración probados.

Solo después se debe planificar HTTPS y sustitución controlada de la versión anterior.
