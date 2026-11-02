# Evidencia de pruebas y limitaciones

La base anterior generada localmente pasó 12 pruebas automatizadas con Python y PyMuPDF, incluyendo casos sintéticos digital y escaneado. **Esta rama GitHub es una reconstrucción y debe validarse independientemente**. La verificación de CI, Docker y despliegue se reportará solo cuando exista un resultado observable.

- `apps/backend/tests/test_ocr.py`: RUT, período, evidencia documental, separación F30-1, PDF digital y detección de tipo.
- `apps/backend/tests/test_api.py`: login, CSRF, carga y cola, Excel y seguridad de formato.
- `.github/workflows/ci.yml`: pruebas backend en Python 3.12 y compilación Vite en Node 22.

No hay aún benchmark representativo sobre Previred escaneado real, ni pruebas de seguridad, rendimiento p95, reproducibilidad Docker o HTTPS en VPS. No procesar documentos laborales reales.
