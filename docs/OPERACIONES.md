# Operación y seguridad — GALANT 2.0

La nueva rama **no se considera apta para producción** hasta finalizar evaluación de seguridad, OCR real, despliegue y backup/restauración. No subir PDFs laborales reales al repositorio público.

## Comprobaciones de instalación

```bash
sudo docker compose ps
sudo docker compose logs --tail=80 api worker proxy
sudo docker compose exec api alembic current
sudo ./scripts/diagnose.sh
```

VPS: Ubuntu 24.04, Docker Compose v2. El instalador detecta puertos ocupados y **no** intenta detener Nginx, Apache ni alterar SSH o firewall. Si 80/443 están ocupados, configurar proxy existente con un administrador.

Acceso externo con documentación real: dominio controlado, HTTPS certificado, `COOKIE_SECURE=true`, sin exposición pública de 5432/8000. Primero ensayar con archivos sintéticos.

## Credenciales

`install.sh` genera claves aleatorias en un archivo `.env` local con permisos 600. No copiar este archivo al repositorio, a chats ni a logs. Crear administrador con `docker compose exec api python -m app.cli create-admin --email correo@empresa.cl` (solicita contraseña interactivamente). Las claves de ejemplos nunca se usan en producción.

## Backups

`backup.sh` necesita `BACKUP_GPG_RECIPIENT` y una clave pública GPG instalada. Produce `pg_dump` y archivo de documentos cifrados, sin persistir texto plano adicional. `restore.sh --confirm-restore` **sobrescribe** la base y restaura documentos solo tras confirmación. Validar este procedimiento en un entorno aislado primero. Programación automática de respaldos y copia fuera del VPS: pendiente.

## OCR

FastAPI no procesa OCR: el worker consulta trabajos PostgreSQL y usa PyMuPDF + Tesseract en CPU. Registra método y extractos por página. No procesa correctamente todos los diseños ni verifica transacciones ante terceros. Ante incertidumbre remite a revisión; medir falsos positivos de pago antes de permitir uso operativo.

## Faltantes explícitos

- Antivirus documental y sandbox para PDF malicioso, política de retención y destrucción de documentos, respuesta a incidentes, registros de lectura y revocación de sesiones.
- Métricas de CPU/RAM y alertas externas, backup programado y ensayado, rollback de migraciones.
- Corpus representativo de cotizaciones Previred escaneadas y benchmark comparado contra el sistema anterior.
- Asistente IA contextual con gestión de consentimiento y confidencialidad.
- Revisión legal chilena vigente de protección de datos personales.

## Actualización

No ejecutar `update.sh` sin backup probado y revisión de cambios. El script usa `git pull --ff-only` y reinicia contenedores, sin rollback automático.
