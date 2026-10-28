# GALANT — lectura F30-1 mejorada

El botón principal **Ejecutar auditoría** ahora detecta automáticamente certificados
F30-1, aunque tengan un nombre distinto y vengan escaneados como imagen sin capa de texto.

## Cómo usarlo

1. Abre la aplicación de Streamlit.
2. En **Sube F30-1, cotizaciones Previred o planillas Excel/CSV**, agrega tu PDF.
3. Haz clic en **Ejecutar auditoría**.
4. Verás arriba el folio, la empresa, el período, los trabajadores declarados
   y los RUT identificados. La nómina aparece en una sección desplegable.
5. Si el PDF contiene solo portada y nómina, el sistema mostrará:
   **«Falta página de resumen; no se puede confirmar el estado de pago»**.
   No significa que el contratista esté impago.

## Qué cambió

- Separa los F30-1 de Previred: nunca los envía al motor de AFP/Fonasa/Mutual
  como si fueran planillas de cotizaciones.
- El OCR utiliza Tesseract y PyMuPDF con relectura de tabla a mayor contraste,
  reconocimiento por coordenadas de RUT y nombres, y fallback OpenCV para
  separar celdas.
- Controla el dígito verificador de cada RUT y compara la nómina detectada
  con **Total Trabajadores** impreso.
- Reconoce período dentro del certificado y no lo sustituye por el mes
  del nombre del PDF (por ejemplo, archivo OCTUBRE, período SEPTIEMBRE).
- Mantiene los certificados separados por folio y muestra advertencias claras
  cuando falta una página o un dato.

## Pruebas

Se comprobó localmente el lector con tres PDFs reales aportados para diagnóstico,
**sin subir ninguno al repositorio público**:
- Salamanca Cerda: 2 de 2 RUT, septiembre 2026; falta página de resumen.
- Chávez y Cifuentes: 4 de 4 RUT, septiembre 2026; pago declarado en el PDF.
- Servicios de Pintura F&B: 5 de 5 RUT, septiembre 2026; pago declarado en el PDF.

GitHub Actions ejecuta tests sintéticos que no contienen documentos laborales reales.

## Límites

La extracción OCR no puede garantizar precisión total en todos los escaneos
y no implica validación de autenticidad en el portal de la Dirección del Trabajo.
No se inventan RUT ni el estado de cotizaciones. Para comprobar autenticidad
utiliza https://verificador.dirtrab.cl/.

El repositorio es público. No subas PDF reales, RUT, claves ni nóminas.
GALANT no incluye chat ni envía certificados F30-1 a servicios externos de IA.
