# GALANT v17 · Referencias y mejoras verificables

Esta revisión usa **información pública** de plataformas chilenas de gestión de contratistas y sistemas internacionales de procesamiento inteligente de documentos. No se ha copiado código de servicios propietarios, importado sus datos ni contratado sus API.

## Comparación técnica

| Plataforma | Práctica documentada públicamente | Aplicación en GALANT | Estado |
|---|---|---|---|
| Pronexo (Chile) | Revisión de pagos previsionales, contratos, alertas y trazabilidad | Bandeja de pendientes por área y evidencia, sin confundir datos faltantes con impagos | Implementado para F30-1/Previred |
| Vasti (Chile) | Revisión documental con observaciones trazables y seguimiento | Hallazgo, archivo, página y acción para cada caso | Implementado |
| ControlDoc (Latam) | OCR, revisión documental, reportes y expedientes | Excel único con ocho hojas: revisión, F30, cotizaciones y cruces | Implementado |
| Rossum | Validación por campo y cola de excepciones de baja certeza | Casos ALTA/MEDIA/BAJA revisables; ningún cambio automático a cifras | Implementado parcialmente; prioridades son reglas, no probabilidades de un modelo |
| Azure Document Intelligence | Confianza por campo, respaldo del dato en documento | Etiquetas de estado de extracción y evidencia por página, sin inventar porcentajes OCR | Implementado parcialmente |
| Google Document AI | Comparación contra muestras etiquetadas y evaluación de falsos positivos/negativos | Pruebas sintéticas y regresiones automáticas. Corpus privado de PDFs reales aún no incorporado | Parcial |
| OCRmyPDF | Corrección de páginas giradas, OCR por página y limpieza de imágenes | Giro selectivo si el lector F30-1 no encuentra palabras de estructura | Implementado con Tesseract/PyMuPDF; sin dependencia OCRmyPDF |
| PyMuPDF | Aprovechar texto digital y ejecutar OCR solo donde hace falta | No volver a rasterizar páginas digitales legibles | Implementado |
| PrevenApp | Estados documentales y evidencia por trabajador | Bandeja de casos para revisar, sin dictamen de habilitación | Implementado parcialmente |

## Enlaces públicos de referencia

- Pronexo: https://www.pronexo.cl/soluciones/
- Vasti: https://vasti.cl/
- ControlDoc: https://controldoc.app/
- Rossum: https://rossum.app/api/docs/openapi/internal/guides/automation/
- Azure Document Intelligence: https://learn.microsoft.com/en-us/azure/ai-services/document-intelligence/concept-accuracy-confidence
- Google Document AI: https://docs.cloud.google.com/document-ai/docs/evaluate
- OCRmyPDF (MPL-2.0): https://github.com/ocrmypdf/OCRmyPDF
- PyMuPDF: https://pymupdf.readthedocs.io/en/latest/ocr/index.html
- PrevenApp: https://prevenapp.cl/
- Dirección del Trabajo (antecedentes F30-1): https://www.dt.gob.cl/portal/1628/w3-article-94246.html

## Cambios de la versión 17

### A. Bandeja priorizada de revisión

La pestaña **Qué revisar** muestra casos agrupados y ordenados por urgencia operacional:
- ALTA: nómina F30-1 incompleta, empleador/período ausentes o documento sin procesar.
- MEDIA: cotizaciones de otro período, OCR parcial, documento sin resumen y RUT ausente en cruce.
- BAJA: archivos exactamente repetidos que el sistema omitió.

La prioridad **no equivale a un juicio jurídico** ni reemplaza la revisión del documento original.

### B. Revisión sin alertas masivas

Si Previred no corresponde al período del F30-1, se crea **un aviso por certificado**, no una fila duplicada por cada trabajador. Los campos problemáticos de Previred siguen mostrando su RUT y páginas de referencia.

### C. Informe único Excel

El botón **Descargar informe completo GALANT** genera estas hojas:
1. Resumen
2. Bandeja_Revision
3. Certificados_F301
4. Cruce_Resumen
5. Cruce_Trabajadores
6. Cotizaciones
7. Procesamiento
8. OCR_F301

El Excel se genera en memoria, incluye el origen de los hallazgos y se protege contra la interpretación de texto como fórmulas.

### D. OCR adaptativo de F30-1

El lector primero extrae texto digital. Solo si no encuentra una estructura documental suficiente intenta OCR y, cuando es necesario, rotaciones de 90, 270 o 180 grados. Esto puede mejorar escaneos girados. El resultado depende de resolución, contraste, páginas presentes y calidad del original.

### E. Pruebas automatizadas

Se incluyen pruebas sin RUT ni PDF de trabajadores reales, cubriendo prioridades, F30-1 incompletos, coincidencia de nóminas, omisiones en Previred, OCR girado e informe Excel válido.

## Límites para una evolución posterior

- No se ha implementado autenticación con roles, repositorio privado de evidencias ni flujos de aprobación persistentes.
- Un F30-1 no debe clasificarse como vencido sin una regla explícita de corte por mes/obra y documentación contractual.
- No se hace verificación automática de autenticidad en el portal DT.
- No existe un índice de confianza **calibrado** por OCR; el sistema utiliza reglas verificables, no porcentajes arbitrarios.
- No se sustituyen comprobantes de pago reales por sumas de bases imponibles.
- No se agregan PaddleOCR, Rossum, ABBYY, Azure ni Google Document AI al servidor: implicarían otros costos, hardware, datos o acuerdos.
- Los PDFs laborales no deben subirse al GitHub público, ni mezclarse con ejemplos sintéticos.

La forma correcta de medir mejoras futuras consiste en crear **un conjunto privado de prueba** con el texto verificado por personas y medir tasa de RUT completos, errores de cifras, falsas alarmas y tiempo de procesamiento por documento antes de desplegar.
