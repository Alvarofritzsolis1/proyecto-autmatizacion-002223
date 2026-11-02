# GALANT 2.0 — Enterprise Document Intelligence Platform

**Reconstrucción del repositorio original en una rama nueva, sin Streamlit.** Software web React/TypeScript + FastAPI/Python + PostgreSQL + trabajador OCR + Caddy/Docker Compose. Especializado inicialmente en análisis de evidencia de cotizaciones chilenas, F30-1 y cotizantes independientes.

> **Estado: implementación fundacional, aún NO apta para procesar información laboral real en producción.** Se verificó el backend y pruebas sintéticas; faltan pruebas representativas de precisión OCR, auditoría de seguridad, ejecución íntegra Docker/Frontend, HTTPS y restauración en tu VPS. Ningún resultado es una confirmación bancaria, ante Previred ni ante la DT.

## Qué está construido

- Interfaz React/Vite/TypeScript original: login, panel, módulos independientes, carga, vista PDF, evidencia, exportación Excel, contratistas, historial y monitoreo básico para administrador.
- FastAPI con sesiones firmadas en cookies HttpOnly, protección CSRF y roles (`admin`, `analyst`, `viewer`).
- Separación por organización en las consultas a base de datos y almacenamiento de archivos en disco privado.
- Recepción real de PDF e imágenes con controles de extensión, firma PDF, estructura de archivo, límite de peso/páginas y deduplicación SHA-256.
- Cola persistente en PostgreSQL: el worker usa `FOR UPDATE SKIP LOCKED` y recupera trabajos estancados.
- Motor OCR híbrido: extracción de texto digital con PyMuPDF, evaluación de páginas mixtas y OCR local Tesseract, orientación OSD cuando funciona y contraste selectivo si es necesario. Trazas por página, tokens y confianza OCR.
- Identificación inicial de RUT válido, período y evidencia de comprobante/estado/folio. **Es un clasificador conservador inicial, no un sistema validado para todos los formatos Previred**.
- Docker Compose, instalador, migración Alembic, configuración de dominio opcional, copias cifradas con GPG y CI de backend/frontend.

## Arquitectura

```text
Navegador (React)  -->  Caddy HTTPS  -->  FastAPI API  -->  PostgreSQL
                                |               |
                                +-- frontend    +-- volumen privado
                                                     ^
                                             worker OCR (PostgreSQL jobs)
```

**No existe ninguna dependencia Streamlit en el código nuevo.** El proyecto heredado se consulta únicamente como fuente de problemas documentados y de reglas que se evaluarán antes de una posible incorporación.

## Instalación en VPS Ubuntu 24.04

**IMPORTANTE:** Configura un dominio apuntando al VPS antes de utilizar datos laborales. El modo sin dominio usa HTTP y es exclusivamente de ensayo. Comprueba que no existan aplicaciones usando los puertos 80 y 443. No ejecutar scripts de terceros sin revisarlos previamente.

1. La nueva aplicación está en la rama `refactor/galant-2-react-fastapi-20261102` de este repositorio. Hasta completar la revisión, `main` conserva la aplicación antigua.
2. En el VPS, instala Git y clona la rama de GALANT 2.0:

   ```bash
   cd /opt
   sudo git clone --branch refactor/galant-2-react-fastapi-20261102 https://github.com/Alvarofritzsolis1/proyecto-autmatizacion-002223.git galant-2
   cd /opt/galant-2
   ```

   Para un repositorio privado configura autenticación segura en Git sin introducir tokens en la URL ni almacenarlos en scripts.

3. Inicia la generación de secretos (Docker Engine/Compose deben existir, o usa `--install-docker`):

   ```bash
   sudo ./install.sh --install-docker
   ```

4. **Para acceso público seguro**, edita `.env` antes de publicar y establece `GALANT_SITE=tu-dominio.cl` y `COOKIE_SECURE=true`; luego vuelve a ejecutar `sudo ./install.sh`. Configura DNS `A` hacia tu VPS y verifica un certificado HTTPS válido. No insertes tu contraseña en la consola por chat.
5. Crea un administrador (contraseña solicitada interactivamente, nunca guardada en Git):

   ```bash
   sudo docker compose exec api python -m app.cli create-admin --email admin@tuempresa.cl --organization 'Mi Empresa'
   ```

6. Visita `https://tu-dominio.cl`, ingresa y **prueba primero documentos sintéticos**, no documentación laboral real.

El instalador crea `.env` con claves aleatorias, comprueba CPU/RAM/disco, evita ocupar puertos de servicios ajenos, construye imágenes, monta volúmenes, aplica migración y revisa la salud de API. No cambia SSH ni firewall. Docker reinicia servicios tras reinicios del VPS (`restart: unless-stopped`).

Si el servidor ya tiene otro servicio web en 80/443, **detente** y configura una convivencia mediante proxy: el instalador no desinstala ni detiene el servicio anterior.

## Desarrollo local

Backend requiere Python 3.12 y Tesseract con idioma español/inglés. Para ejecutar con SQLite únicamente en desarrollo:

```bash
cd apps/backend
python -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt
export APP_SECRET="$(python -c 'import secrets; print(secrets.token_hex(48))')"
export DATABASE_URL='sqlite:///./galant-dev.db'
export OCR_LANG='eng'
python -m app.cli init-db
python -m app.cli create-admin --email admin@example.cl
uvicorn app.main:app --reload
```

Terminal aparte:

```bash
cd apps/backend
source .venv/bin/activate
# Exportar las mismas variables de entorno de backend
python -m app.worker
```

Frontend:

```bash
cd apps/frontend
npm install
npm run dev
```

Abre `http://localhost:5173`. Vite hace proxy a FastAPI puerto 8000. Sin instalar dependencias NPM el frontend no puede ejecutarse, aunque su código fuente ya esté escrito.

## Criterio documental

- **Pago acreditado documentalmente**: se observa en una página un comprobante, un estado de pago explícito, un identificador transaccional y un período. Aun así, no significa que se haya corroborado la operación oficialmente.
- **Pago no acreditado**: el archivo no entrega evidencia suficiente o indica declaración sin pago; **no prueba impago**.
- **Pendiente de revisión**: evidencia ambigua, dispersa, OCR poco confiable o F30-1 aislado para efectos de pago.
- **Documento ilegible**: extracción insuficiente.
- **Documento incorrecto**: tipo no corresponde al módulo.

Para escenarios reales, **un profesional debe verificar la evidencia original**. La precisión del clasificador inicial depende del formato y debe medirse antes de autorizar decisiones automáticas.

## Comprobaciones que puedes ejecutar

```bash
cd apps/backend && python -m pytest -q
cd ../frontend && npm run build
cd ../.. && docker compose config --quiet
./scripts/diagnose.sh
```

## Restricciones e hitos pendientes

| Estado | Función |
| --- | --- |
| Implementado con pruebas sintéticas | Backend, login, flujo de carga/worker, PyMuPDF/Tesseract, lectura híbrida, evidencia inicial, Excel |
| Implementado pero sin build verificado aquí | UI React, navegación, carga, visor, panel y contratistas |
| Definido pero sin prueba de VPS | Docker Compose, Caddy, instalador, backup/restore, servicio 24/7 |
| Pendiente | Benchmark con PDFs reales anonimizados y trazabilidad del pago por institución/trabajador |
| Pendiente | Parser avanzado Previred por tablas/celdas y recuperación fiable de nóminas |
| Pendiente | Evaluación de RapidOCR/PaddleOCR/Document AI, costo/precisión/latencia |
| Pendiente | IA conversacional opcional con controles de confidencialidad y validación humana |
| Pendiente | Evaluación de pentesting, escaneo antimalware de documentos, revisiones de privacidad, rotación/revocación de sesiones |
| Pendiente | Observabilidad avanzada, reportes multi-contratista, políticas de retención, backups automatizados y prueba de rollback |
| Pendiente | Verificar RAM/CPU/almacenamiento real de tu VPS y validar HTTPS/restore |

Ver `docs/AUDITORIA_ORIGEN.md` y `docs/OPERACIONES.md`.