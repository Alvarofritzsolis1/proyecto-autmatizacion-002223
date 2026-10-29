# GALANT — Implementación de Vercel + Supabase (estado técnico)

La interfaz **Next.js** está en `web/`, el lector OCR sigue en Python
(`pago_documental.py` y `f301_lector.py`) y los trabajos se consumen
desde `worker/worker.py`. **No es correcto instalar solo Vercel y declarar
GALANT operativo:** también requiere Supabase y un trabajador Python en ejecución.

## 1. GitHub y Vercel

- Repositorio: `Alvarofritzsolis1/proyecto-autmatizacion-002223`
- Rama: `feature/galant-vercel-supabase` (requiere PR #10 del OCR).
- Crear proyecto `galant` en el equipo autorizado.
- Framework: **Next.js**.
- Root Directory: **web** (no raíz del repositorio).
- Runtime Node.js: **22.x**.
- Mantener protegidos los despliegues de prueba. No promocionar a producción
  sin comprobar login, RLS, y procesamiento de documentos.
- Confirmar el resultado del workflow `GALANT web - build de validación`.

## 2. Proyecto Supabase

Un proyecto real necesita autorización de su propietario. Ejecutar en SQL Editor
por orden los archivos:

1. `supabase/migrations/20261029_galant_secure.sql`
2. `supabase/migrations/20261029_galant_retries.sql`

Configuración:
- Activar autenticación por correo y crear/invitar al usuario autorizado.
- El front usa `shouldCreateUser:false` para impedir altas públicas desde GALANT.
- Configurar **Site URL** y la lista de **Redirect URLs** de Supabase Auth
  para el dominio real y los previews autorizados de Vercel.
- Confirmar bucket **privado** `galant-documentos`, RLS para documentos y
  restricciones de acceso por `auth.uid()`.

En Vercel / Environment Variables (Production/Preview según corresponda):

- `NEXT_PUBLIC_SUPABASE_URL` — URL HTTPS del proyecto.
- `NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY` — clave **publicable**, nunca secret.

**NUNCA subir claves privadas a GitHub, al navegador o al chat.**

## 3. Trabajador OCR (servicio separado)

El despliegue de Vercel muestra la interfaz, pero los PDF requieren un
servicio Python aparte. En su entorno de ejecución privado configurar:

- `SUPABASE_URL`
- `SUPABASE_SECRET_KEY` — solo servidor, nunca en Vercel frontend.
- `GALANT_MAX_OCR_PAGES` — opcional; valor inicial 12.
- `GALANT_POLL_SECONDS` — opcional; valor inicial 10.

Contenedor (si se cuenta con un servicio Docker persistente):

```sh
docker build -f worker/Dockerfile -t galant-ocr .
docker run --rm --env-file /RUTA/PRIVADA/worker.env galant-ocr
```

No almacenes `worker.env` en el repositorio. Asegurar firewall y monitoreo
del servicio; `--once` sirve solo para procesar trabajos actuales.

## 4. Prueba de extremo a extremo (sin datos personales)

1. Iniciar sesión con un usuario invitado.
2. Subir un PDF **sintético**, no un comprobante real.
3. Verificar la fila `pendiente` en Supabase.
4. Ejecutar trabajador OCR y comprobar transición a `completado`
   o `requiere_revision`, con período y fecha correctamente asociados.
5. Verificar que otra cuenta no pueda leer el PDF, el resultado ni cambiar
   el estado de la primera.
6. Verificar que un PDF ilegible **nunca** implique `no pagado`.
7. Revisar logs, tiempos, períodos, folios, y cobertura de páginas OCR.

## Restricciones actuales

- El motor OCR no determina autenticidad oficial de los comprobantes.
- Los resultados pueden ser parciales en documentos multifolio; deben
  mostrar esas limitaciones.
- Vercel no ejecuta aquí automáticamente Tesseract: el worker es
  un proceso independiente y requiere alojamiento propio.
- No desplegar el frontend con datos laborales hasta que la seguridad RLS
  y almacenamiento privados se hayan comprobado.
