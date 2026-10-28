# Revisión técnica del pipeline de auditoría laboral

## Hallazgos del diseño previo

1. **Tope imponible fijo en el código.** Un importe fijo en CLP no sirve para todos los períodos ni se actualiza con cambios oficiales. La app nueva no inventa topes: permite cargar una tabla `periodo_remuneracion,tope_imponible_clp`, que debe verificarse y mantenerse por el usuario.
2. **Mutual por defecto.** Asignar ISL cuando el documento no identifica la entidad produce información inventada. Ahora se informa `NO IDENTIFICADA` y la fila pasa a `REVISAR_DATOS`.
3. **Período por defecto.** Reemplazar un período ausente por el mes actual puede adjudicar la remuneración a un período incorrecto. Ahora se completa solo si se infiere un patrón explícito del nombre del archivo; de lo contrario queda pendiente.
4. **Extracción PDF demasiado rígida.** Las expresiones regulares/posiciones exactas fallan al cambiar la disposición de tablas, cabeceras o páginas. La nueva versión intenta extraer tablas seleccionables, detecta cabeceras y evita inventar valores. Los PDF escaneados aún necesitan OCR.
5. **Errores numéricos convertidos silenciosamente a cero.** Un texto no numérico podía parecer un cero verdadero y generar una conformidad falsa. La versión actual conserva marcas internas de datos ausentes/incorrectos y deriva la fila a revisión.
6. **Consolidación automática de duplicados.** Sumar filas repetidas puede duplicar días y rentas cuando el archivo repite una página o se carga el mismo registro en dos fuentes. Ahora los duplicados se señalan y no se suman automáticamente.
7. **Conformidad sin datos suficientes.** Días vacíos, bases ausentes o valores dudosos no deben interpretarse como datos válidos. Esos casos quedan en `REVISAR_DATOS`.
8. **Excel con contenido potencialmente activo.** El texto importado que comience con `=` podría ser interpretado por Excel como fórmula. La exportación desactiva la interpretación automática de fórmulas y enlaces para esas cadenas.
9. **Errores sin trazabilidad.** El pipeline registra por archivo si pudo procesarlo o por qué lo omitió; el Excel incluye las hojas `Matriz_Auditoria`, `Detalle_Revision` y `Log_Procesamiento`.

## Qué está automatizado

- Carga múltiple de Excel, CSV y PDF con texto/tablas seleccionables desde Streamlit.
- Detección de cabeceras, mapeo de sinónimos, normalización de RUT/período/montos, filtros de filas de resumen y controles de integridad.
- Reglas explícitas de alerta, detalle de hallazgos, exportación corporativa y pruebas automáticas al modificar el repositorio.

## Límites que siguen requiriendo revisión

- No hay OCR integrado. Los PDF escaneados se informan como no procesables, en vez de dar un resultado dudoso.
- Los formatos de Previred pueden variar; hay que probar la extracción con ejemplos representativos de los PDFs reales antes de usarla para una auditoría operativa.
- No se calculan tasas ni se confirman pagos efectivos; se comparan los valores declarados en los archivos.
- El tope por período no se descarga desde una fuente legal: debe comprobarse oficialmente y cargarse en el CSV opcional.
- Las diferencias entre salud, AFP y mutual deben revisarse conforme al procedimiento laboral aplicable. La igualdad de bases, por sí sola, no demuestra que todas las obligaciones estén pagadas.

## Validación efectuada en este entorno

- `python -m compileall -q app.py auditoria_laboral.py test_auditoria_laboral.py`: correcto.
- `python -m pytest -q`: 1 suite de regresión aprobada; 1 prueba de interfaz omitida porque Streamlit no estaba instalado en el entorno local.
- `python test_auditoria_laboral.py`: pruebas funcionales de regresión completadas correctamente.

La prueba de interfaz se ejecuta en GitHub Actions con las dependencias instaladas. La publicación real en Streamlit Community Cloud debe validarse después de desplegar desde tu repositorio.


## Corrección solicitada por error de PDF escaneado

Se agregó OCR automático para páginas candidatas usando PyMuPDF + Tesseract (idiomas español/inglés). En Streamlit Community Cloud se instalan los binarios mediante `packages.txt`; `requirements.txt` instala los módulos Python. El sistema intenta reconstruir la tabla con métodos alternativos y, si no puede hacerlo de forma confiable, genera un error explícito en vez de auditar datos parciales. El OCR no garantiza extraer cualquier diseño de planilla; el resultado debe verificarse con el documento original.

## Reparación basada en comprobante real de Previred (octubre de 2026)

**Causa raíz identificada:** la estrategia de extracción PDF anterior esperaba cabeceras planas similares a Excel. Los comprobantes de Previred contienen cabeceras jerárquicas, datos repetidos de un mismo RUT en varias instituciones y múltiples movimientos personales. Al intentar reconstruir un DataFrame directamente desde las tablas del PDF, no se identificaba una columna única de días reales, incluso cuando el OCR producía texto.

**Cambio estructural:** se incorporó `previred_pdf.py` que identifica secciones por su encabezado, separa registros por fuente (Seguro Social, Salud, AFP, ISL/Mutual), extrae las posiciones de datos conocidas solo si el patrón es compatible y cruza por RUT válido. No suma montos entre instituciones. Suma días solo dentro de la misma fuente, conserva la evidencia de página y comprueba totales declarados del documento.

**Prueba ejecutada con el archivo de ejemplo:** 10 páginas, 2 trabajadores, período 2026-02 (aunque el archivo se llame 2026-MARZO). Días 2 y 1; bases imponibles Salud/AFP/ISL de 35.933 y 22.459 pesos; total 58.392 pesos por fuente. Ambos pasan el motor de comparación definido. Esta conformidad no certifica cotización pagada, contratos, afiliación ni cumplimiento laboral integral.

**Limitación pendiente:** no se ha validado esta versión con el PDF escaneado de Constructora Buffalo del mensaje anterior porque no se ha proporcionado ese documento original. Los formatos y niveles de OCR diferentes pueden requerir ajustes adicionales. Los fallos se muestran como errores de extracción o `REVISAR_DATOS`; nunca deben convertirse silenciosamente en `CONFORME`.


## Diagnóstico del error con PDF de Constructora Buffalo (lectura local)

**Causa raíz:** las 12 páginas son imágenes de documentos girados; el OCR
original procesaba páginas completas y buscaba cabeceras en texto lineal.
La posición de los datos en las tablas escaneadas se pierde en OCR de página
completa, por lo que las cabeceras de trabajadores no se reconocían de forma
fiable y aparecía el mensaje «se aplicó OCR pero no se pudieron identificar
las columnas».

**Corrección:** `previred_scan_fast.py` identifica los bordes de tablas usando
píxeles, sin OCR de texto general. En el comprobante estudiado separa los
anexos de ACHS, AFP, Fonasa y Seguro Social, y pasa a Tesseract únicamente
los recortes de datos individuales. Usa un OCR de lote por página y hace
reintentos de celdas ambiguas, sin calcular tasas por defecto. Registra
cotejos y advertencias, e impide que el OCR genere conformidad automática.

**Resultados verificados:** 8 personas, 51 días, 916.299 CLP de renta imponible
por fuente (Salud, AFP y ACHS); período 2026-04, aunque el archivo se titula
2026-MAYO por su fecha de pago. Se conservan las 11 columnas de la matriz.

**Protecciones:** se conserva el procesamiento por memoria, validación de RUT,
registro de fuentes, rechazo de campos vacíos como evidencia de 0, y estados
de revisión de información OCR. No se publican los documentos reales en GitHub.
