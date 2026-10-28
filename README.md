# GALANT · Control documental de contratistas

**GALANT** es una aplicación Streamlit para revisar cotizaciones previsionales (AFP, Salud, Mutual/ISL, Seguro Social) y certificados F30-1. Coteja empleadores, períodos y RUT por documento, revisa bases y presenta observaciones accionables.

**No necesita API de pago ni servicios de IA.** Se retiró el chat de Gemini de la aplicación.

## Cómo usarlo

1. Sube los documentos PDF digitales o escaneados, Excel o CSV.
2. Haz clic en **Analizar documentos**.
3. En **Resumen y cruce**, verifica la correspondencia F30-1/Previred.
4. En **Certificados F30-1**, ve empresa, folio, período, RUT recuperados y el estado declarado en el PDF.
5. En **Cotizaciones y detalle**, revisa únicamente filas con observaciones y descarga el Excel.
6. Descarga el CSV del cruce de nóminas cuando hayas cargado ambas fuentes.

Las opciones de tolerancia y topes quedan ocultas por defecto; archivos exactamente duplicados se omiten para no contar dos veces los mismos datos.

## Mejoras incorporadas

**Clasificación:** Los F30-1 se separan de AFP/Salud/Mutual antes de ejecutar el motor de cotizaciones. El nombre del archivo no reemplaza la inspección de su contenido.

**OCR:** Se emplean extracción digital, Tesseract y rescate especializado de tablas. Se verifica el dígito del RUT y se contrasta el total de trabajadores contra los identificados. Si falta una página de resumen, se informa documentación incompleta, no impago.

**Previred:** Las diferencias de AFP y Seguro Social se asignan al RUT afectado, no a toda la nómina. Un OCR con tres bases concordantes, días e identidad completos no recibe una alerta técnica genérica; las lecturas incompletas siguen en revisión.

**Cruce F30-1/Previred:** Coinciden solo documentos del mismo empleador y período; se busca cada RUT de la nómina F30-1 en Previred. No se exige igualdad entre la nómina de una obra y toda la nómina empresarial.

**Trazabilidad:** Detalles, páginas de origen, hallazgos y acción recomendada para cada caso. Descarga Excel de cotizaciones y CSV del cruce documental.

**Eficiencia:** Dependencias ML trasladadas a desarrollo/CI, controles no usados se mantienen ocultos, archivos iguales no se procesan duplicados y la auditoría pesada se ejecuta solo al pulsar el botón.

**Calidad:** Pruebas automáticas en GitHub Actions, incluyendo conciliación de dos empresas, períodos diferentes, trabajadores faltantes y duplicados.

## Instalación

En Streamlit Community Cloud selecciona la rama principal del repositorio y el archivo principal **app.py**. Los archivos **requirements.txt** y **packages.txt** incluyen las dependencias del servidor. No hace falta configurar ninguna clave de Gemini ni de OpenAI.

## Seguridad y límites

- **El repositorio GitHub es público.** No publiques PDF laborales, nóminas, RUT, claves ni remuneraciones. Configura acceso restringido a Streamlit para procesar información personal.
- El estado de pago que muestra el F30-1 es un dato extraído del propio PDF. No es una consulta autenticada a la Dirección del Trabajo.
- Verificador DT: https://verificador.dirtrab.cl/
- La coincidencia de bases, trabajadores y períodos no acredita por sí sola pago legal o cumplimiento de obligaciones laborales.
- Un PDF incompleto o ilegible no debe etiquetarse automáticamente como impago.
- Ningún OCR garantiza lectura perfecta del 100 % de los escaneos.

## Referencias públicas para decisiones de diseño

- Revisión humana de casos inciertos: https://www.abbyy.com/ai-document-processing/human-in-the-loop-verification/
- Validación por confianza y anomalías: https://rossum.app/api/docs/openapi/internal/guides/automation/
- OCR selectivo con PyMuPDF: https://pymupdf.readthedocs.io/en/latest/ocr/index.html
- Buenas prácticas de rendimiento Streamlit: https://docs.streamlit.io/develop/concepts/architecture/caching

Se utilizaron ideas de diseño públicas, no código propietario ni productos de pago.

## Estado de versiones

GALANT se actualiza sobre el código realmente alojado en este GitHub. Otros paquetes experimentales creados fuera del repositorio no se consideran instalados hasta integrarlos y probarlos.
