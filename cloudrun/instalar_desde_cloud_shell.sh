#!/usr/bin/env bash
# GALANT — instalar desde Google Cloud Shell con sesión del titular.
# Requiere: proyecto con facturación autorizada y migraciones Supabase aplicadas.
set -euo pipefail

PROJECT_ID="$(printenv GALANT_PROJECT_ID 2>/dev/null || true)"
REGION="us-central1"
JOB="galant-ocr"
RUNTIME_SA="galant-ocr-runtime"
SCHEDULER_SA="galant-ocr-scheduler"
FREQ="*/15 * * * *"

if [[ -z "$PROJECT_ID" ]]; then
  read -r -p "ID de tu proyecto Google Cloud: " PROJECT_ID
fi
if [[ ! "$PROJECT_ID" =~ ^[a-z][a-z0-9-]{5,28}[a-z0-9]$ ]]; then
  echo "ID de proyecto inválido." >&2; exit 2
fi
PROJECT_NUMBER="$(gcloud projects describe "$PROJECT_ID" --format='value(projectNumber)')"
if [[ -z "$PROJECT_NUMBER" ]]; then
  echo "No se encontró el proyecto o faltan permisos." >&2; exit 2
fi
BILLING="$(gcloud billing projects describe "$PROJECT_ID" --format='value(billingEnabled)' 2>/dev/null || true)"
if [[ "$BILLING" != "True" ]]; then
  echo "Vincula facturación desde Google Cloud Console; no puedo aprobarla por ti." >&2
  exit 2
fi
echo "GALANT: Cloud Run Jobs, 1 CPU, 2 GiB, us-central1, cada 15 minutos."
echo "El nivel gratuito NO garantiza gasto cero. Controla costos en Billing."
read -r -p "¿Autorizas la instalación de recursos en este proyecto? Escribe SI: " CONFIRM
[[ "$CONFIRM" == "SI" ]] || { echo "Cancelado."; exit 1; }
echo "Debes aplicar en Supabase la migración inicial, retries y vision_budget."
read -r -p "¿Ya aplicaste las 3 migraciones en Supabase? Escribe SI: " CONFIRM_SQL
[[ "$CONFIRM_SQL" == "SI" ]] || { echo "No se desplegó el OCR."; exit 2; }

gcloud config set project "$PROJECT_ID" >/dev/null
gcloud services enable \
    run.googleapis.com cloudbuild.googleapis.com artifactregistry.googleapis.com \
    vision.googleapis.com cloudscheduler.googleapis.com secretmanager.googleapis.com \
    iam.googleapis.com --project "$PROJECT_ID"

RUNTIME_EMAIL="$RUNTIME_SA@$PROJECT_ID.iam.gserviceaccount.com"
SCHEDULER_EMAIL="$SCHEDULER_SA@$PROJECT_ID.iam.gserviceaccount.com"
if ! gcloud iam service-accounts describe "$RUNTIME_EMAIL" --project "$PROJECT_ID" >/dev/null 2>&1; then
  gcloud iam service-accounts create "$RUNTIME_SA" \
      --display-name="GALANT OCR" --project "$PROJECT_ID"
fi
if ! gcloud iam service-accounts describe "$SCHEDULER_EMAIL" --project "$PROJECT_ID" >/dev/null 2>&1; then
  gcloud iam service-accounts create "$SCHEDULER_SA" \
      --display-name="GALANT Scheduler" --project "$PROJECT_ID"
fi
gcloud projects add-iam-policy-binding "$PROJECT_ID" \
    --member="serviceAccount:$RUNTIME_EMAIL" \
    --role="roles/serviceusage.serviceUsageConsumer" --quiet >/dev/null

# Contraseñas capturadas solo dentro de Cloud Shell.
if ! gcloud secrets describe galant-supabase-url --project "$PROJECT_ID" >/dev/null 2>&1; then
  read -r -p "URL del proyecto Supabase (https://...supabase.co): " SUPABASE_URL_INPUT
  [[ "$SUPABASE_URL_INPUT" =~ ^https://[a-z0-9-]+\.supabase\.co/?$ ]] || {
    echo "URL inválida."; exit 2;
  }
  printf '%s' "$SUPABASE_URL_INPUT" |
    gcloud secrets create galant-supabase-url --project "$PROJECT_ID" \
      --replication-policy=automatic --data-file=- >/dev/null
  unset SUPABASE_URL_INPUT
fi
if ! gcloud secrets describe galant-supabase-secret --project "$PROJECT_ID" >/dev/null 2>&1; then
  read -r -s -p "Clave secreta Supabase (se oculta al escribir): " SUPABASE_KEY_INPUT
  echo
  [[ -n "$SUPABASE_KEY_INPUT" ]] || { echo "Falta clave"; exit 2; }
  printf '%s' "$SUPABASE_KEY_INPUT" |
    gcloud secrets create galant-supabase-secret --project "$PROJECT_ID" \
      --replication-policy=automatic --data-file=- >/dev/null
  unset SUPABASE_KEY_INPUT
fi
for secret in galant-supabase-url galant-supabase-secret; do
  gcloud secrets add-iam-policy-binding "$secret" \
      --member="serviceAccount:$RUNTIME_EMAIL" \
      --role="roles/secretmanager.secretAccessor" \
      --project "$PROJECT_ID" --quiet >/dev/null
done

echo "Construyendo y desplegando GALANT OCR en Cloud Run Jobs..."
gcloud run jobs deploy "$JOB" \
    --source . \
    --region "$REGION" \
    --project "$PROJECT_ID" \
    --service-account "$RUNTIME_EMAIL" \
    --tasks 1 --parallelism 1 --max-retries 0 \
    --task-timeout 900s --cpu 1 --memory 2Gi \
    --set-env-vars "GALANT_VISION_ENABLED=true,GALANT_VISION_MAX_MES=300,GALANT_VISION_MAX_DIA=20,GALANT_VISION_MAX_PAGINAS_PDF=2,GALANT_MAX_OCR_PAGES=12" \
    --set-secrets "SUPABASE_URL=galant-supabase-url:latest,SUPABASE_SECRET_KEY=galant-supabase-secret:latest" \
    --quiet

gcloud run jobs add-iam-policy-binding "$JOB" \
    --region "$REGION" --project "$PROJECT_ID" \
    --member="serviceAccount:$SCHEDULER_EMAIL" \
    --role="roles/run.invoker" --quiet >/dev/null

URI="https://run.googleapis.com/v2/projects/$PROJECT_ID/locations/$REGION/jobs/$JOB:run"
if gcloud scheduler jobs describe galant-ocr-poll --location "$REGION" \
      --project "$PROJECT_ID" >/dev/null 2>&1; then
  gcloud scheduler jobs update http galant-ocr-poll \
      --location "$REGION" --project "$PROJECT_ID" \
      --schedule "$FREQ" --time-zone "America/Santiago" \
      --uri "$URI" --http-method POST \
      --oauth-service-account-email "$SCHEDULER_EMAIL" \
      --max-retry-attempts 0 --quiet
else
  gcloud scheduler jobs create http galant-ocr-poll \
      --location "$REGION" --project "$PROJECT_ID" \
      --schedule "$FREQ" --time-zone "America/Santiago" \
      --uri "$URI" --http-method POST \
      --oauth-service-account-email "$SCHEDULER_EMAIL" \
      --max-retry-attempts 0 --quiet
fi
echo "Cloud Run y Scheduler configurados. Prueba con un PDF sintético."
echo "Para ejecutar ahora:"
echo "gcloud run jobs execute $JOB --region $REGION --project $PROJECT_ID --wait"
echo "Crear alertas y caps de gasto en Google Cloud Billing."
