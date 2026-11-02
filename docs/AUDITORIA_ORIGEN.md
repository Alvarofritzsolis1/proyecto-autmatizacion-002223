# Auditoría inicial del proyecto anterior

Repositorio: `Alvarofritzsolis1/proyecto-autmatizacion-002223`, rama `main` conservada.

La antigua interfaz está concentrada en `app.py` y depende de Streamlit. Se decidió reemplazarla por React, manteniendo módulos OCR desconectados de la presentación.

## Hallazgos y aprendizajes importantes

- PR #22: páginas escaneadas giradas y tablas previsionales que requieren segmentación de regiones, no solo OCR de texto completo.
- PR #23: el experimento de reconocimiento estricto quedó *draft* por insuficiencia de corpus y falsos positivos numéricos; no se traslada como módulo validado.
- PR #25: existió un error de reconstrucción de tablas digitales (PyMuPDF y planillas Fonasa); usar texto digital antes de OCR cuando sea confiable.
- PR #26: documentos híbridos con partes escaneadas y texto; no abandonar páginas rasterizadas después de detectar capa de texto.
- PR #27: el despliegue VPS del sistema anterior **todavía tiene Streamlit**, por lo que no responde al nuevo objetivo.

## Nueva política

Mantener original como historia recuperable. Construir nueva API OCR con datos trazables, lectura conservadora y componentes separados. La etapa inicial no pretende superar el benchmark anterior sin una evaluación privada de PDFs reales y etiquetas manuales.

Los errores pueden originarse en rasterización, orientación, segmentación de tablas, reconstrucción de columnas, extracción de campos y clasificación de pagos; no etiquetar todo como “fallo de OCR”.

Datos sensibles: nunca subir RUT ni PDF reales a una prueba pública, issue o pull request.
