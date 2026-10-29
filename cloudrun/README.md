# GALANT OCR en Google Cloud Run + Google Vision

## Estado
Este PR prepara el código. **No** crea por sí mismo un proyecto real de Google,
acepta términos de facturación, aplica migraciones en Supabase ni despliega el sitio.
Los PDF privados NO deben subirse a este repositorio público.

Arquitectura:
1. La web Next.js (PR #12) envía PDF a Supabase Storage privado.
2. Postgres guarda un trabajo pendiente en galant_documentos.
3. Cloud Scheduler ejecuta Cloud Run Job cada 15 minutos; el contenedor
   arranca, procesa hasta 3 PDF y termina. Sin computador encendido.
4. Tesseract extrae texto primero. Solo faltantes de pago/período/folio de
   documentos escaneados pueden pasar a Vision OCR si hay cuota.
5. El resultado aparece en Supabase. Nunca confirmar pago bancario/oficial.

## Paso de propietario en Google Cloud
Se necesita:
- Una cuenta con un proyecto Google Cloud de facturación autorizada.
- Permisos para crear Cloud Run Jobs, habilitar APIs, crear cuentas de servicio,
  programar Scheduler y usar Secret Manager.
- Un proyecto Supabase activo con las migraciones:
  1. supabase/migrations/20261029_galant_secure.sql
  2. supabase/migrations/20261029_galant_retries.sql
  3. supabase/migrations/20261029_galant_vision_budget.sql
- Aplicar el frontend del PR #12 en un Vercel con Root Directory web y sus
  variables NEXT_PUBLIC_SUPABASE_URL y NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY.

En https://console.cloud.google.com/ habilitar el proyecto y confirmar
facturación (el titular debe hacerlo; ChatGPT no puede aprobar cargos).

## Instalación desde Google Cloud Shell
Abrir https://shell.cloud.google.com/ con la cuenta propietaria.
Ejecutar:

    git clone --branch feature/galant-cloudrun-vision \
      https://github.com/Alvarofritzsolis1/proyecto-autmatizacion-002223.git galant-cloud
    cd galant-cloud
    bash cloudrun/instalar_desde_cloud_shell.sh

El script:
- Pregunta el ID del proyecto y pide confirmación del titular.
- Verifica que la facturación ya esté habilitada.
- Pide que las migraciones Supabase estén aplicadas.
- Habilita APIs de Cloud Run, Vision, Scheduler, Secret Manager y Cloud Build.
- Crea identidades limitadas; guarda la URL/secret de Supabase en Secret Manager.
- Despliega el trabajo desde el Dockerfile del repositorio en us-central1.
- Programa una llamada autenticada cada 15 minutos.
- No registra ni muestra claves privadas en GitHub.

Luego ejecutar un PDF SINTÉTICO de prueba y comprobar:
    gcloud run jobs execute galant-ocr --region us-central1 --wait

## Protección de costos
Valores iniciales fijados en el deploy:
- GALANT_VISION_ENABLED=true
- GALANT_VISION_MAX_MES=300, máximo absoluto por código 900
- GALANT_VISION_MAX_DIA=20, máximo absoluto por código 30
- GALANT_VISION_MAX_PAGINAS_PDF=2, máximo absoluto por código 3
- Solo se invoca Vision sobre páginas candidatas escaneadas con datos faltantes.
- La reserva Postgres es transaccional, protege contra workers concurrentes.
- Si RPC de cuota falla: NO se envía nada a Vision.
- Un fallo de Vision consume la reserva, una opción conservadora.
- Cloud Run Job: una tarea, 1 vCPU, 2 GiB, 900 s, sin reintentos automáticos.
- Scheduler: una tarea cada 15 minutos; ningún worker permanente.

**No garantiza costo total cero.** Cloud Run, Google Vision, Cloud Scheduler,
Cloud Build, Artifact Registry, Secret Manager, logging, egress y Supabase
tienen sus propios límites/cargos. Hay que configurar presupuestos/alertas
de facturación y, si están disponibles, caps por servicio en
https://console.cloud.google.com/billing. El sistema controla solo las
llamadas de GALANT a Vision; no puede detener otros consumidores de la API.

## Seguridad
- Usa credenciales ADC automáticas de Cloud Run; NO crear archivo JSON de
  cuenta de servicio ni guardar claves Vision en el repositorio.
- El PDF viaja de Supabase privado a Cloud Run y solo la imagen de páginas
  problemáticas se transmite a Google Vision. Evaluar política de privacidad,
  residencia de datos y autorización de tratamiento antes de usar datos reales.
- No registrar OCR, RUT, nombres ni claves en logs. No subir datos de prueba
  reales a GitHub, ni al chat.
- Asegurar Supabase RLS, autenticación invite-only y bucket privado.
- Si una fecha/período no está suficientemente claro, marcar revisión.
- Vision no verifica la autenticidad, validez de pago o cobertura de todos los folios.

## Validación automática
Pruebas sintéticas en tests/test_vision_rescue.py, por ejemplo:
- No llamada Vision sin habilitación.
- No llamada Vision para PDF digital.
- Cuota no disponible -> no llamada.
- Límite máximo de páginas/documento.
- Bloqueo de mezcla de folios o instituciones.
- Distintos estados OCR y fechas incompletas.

## Advertencia de rendimiento
La velocidad de Vision no está medida todavía con los 20 PDF del usuario en
Google Cloud. No afirmar mejoras cuantificadas hasta probar con documentos
autorizados, revisar tiempos y falsos positivos.
