# Migración del repositorio original a GALANT 2.0

**Rama:** `refactor/galant-2-react-fastapi-20261102`

Se sustituye el árbol del proyecto heredado por la nueva estructura React + TypeScript y FastAPI + OCR. Se utiliza un commit con padre `main`, por lo que **el historial completo sigue recuperable**, y la versión Streamlit permanece disponible en `main` hasta que el PR sea revisado y fusionado.

## Política de seguridad

El repositorio original es **público**. No incluir documentos previsionales reales, RUT, credenciales, archivos `.env`, bases de datos, capturas privadas ni backups.

Antes de fusionar o publicar:
1. Verificar que CI ejecuta tests backend y compilación frontend.
2. Ejecutar pruebas Docker en entorno aislado.
3. Obtener un dominio TLS y cambiar `COOKIE_SECURE=true`.
4. Auditar seguridad de archivos PDF maliciosos y tratar normativa chilena aplicable.
5. Etiquetar corpus privado con ejemplos reales (no subir al repositorio).
6. Verificar benchmarks de precisión, especialmente falsos positivos de pago.

## Estado funcional

- Implementados: autenticación básica, separación por organización, carga privada y validada de PDF e imágenes, cola PostgreSQL, extracción digital/escaneada con Tesseract, clasificación documental conservadora, F30-1 por separado, historial, contratistas, visor de evidencia y Excel.
- **Pendiente:** OCR tabular especializado Previred/Isapre/Fonasa comparable con corpus real; antivirus documental; asistentes IA; métricas avanzadas; pruebas de restauración y de despliegue VPS; endurecimiento para producción.
- Un resultado `Pago acreditado documentalmente` **no significa un pago autenticado ante un organismo externo**.

Ningún componente de `main` se borrará hasta completar la revisión y la fusión por GitHub.
