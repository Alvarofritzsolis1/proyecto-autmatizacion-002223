# GALANT — Plan real para eliminar resultados OCR falsamente confiables

**Estado al crear este plan:** el PDF original de Servicios de Pintura F&B muestra en su
anexo Fonasa cinco trabajadores con días **24, 11, 27, 27 y 13**. En una lectura
local de las 19 celdas con la geometría y orientación del lector, las cifras
seleccionadas fueron esas cinco; la pantalla del usuario ha mostrado **24, 2,
sin dato, 27 y 13**. **No está demostrada la causa exacta del desacuerdo en
Streamlit Community Cloud.**

## Fallas comprobadas en el proceso anterior

1. Se presentaron pruebas unitarias con valores sustituidos por mocks como
   si fueran una prueba de extremo a extremo del despliegue.
2. Se publicaron nuevos commits sin comprobar la salida del servidor real.
3. La tabla de Streamlit mezclaba directamente el OCR con la posibilidad de
   editar manualmente los días, dificultando localizar el origen de los valores.
4. La plataforma no mostraba entrada SHA256, la versión de Tesseract/OpenCV,
   orientación por página ni lectura bruta y regla elegida por celda.
5. Si el lector Fonasa lanzaba una excepción controlada, el procesamiento
   devolvía una nómina vacía sin explicación detallada.
6. La geometría de tablas escaneadas depende de resolución, orientación y
   calidad; el éxito en un PDF no demuestra precisión en otros documentos.

## Correcciones de esta entrega

- Cada trabajador trae `traza_dias` por fila: lectura OCR bruta, decisión
  geométrica, cifra aceptada/rechazada, regla y caja en píxeles.
- Se añade una segunda comprobación de coherencia: una cifra se bloquea si
  no corresponde a UNA celda positiva válida de su propio historial.
- En Streamlit se muestran build/version + SHA del módulo Fonasa, versiones
  Python, OpenCV, Tesseract y el SHA256 del PDF cargado.
- La tabla de lectura original queda **solo lectura**. Las correcciones
  humanas están en otra sección y otro CSV con marca de procedencia.
- El usuario puede abrir el recorte real de la celda que **esa misma
  ejecución** eligió y descargar un JSON privado con el diagnóstico.
- Si el lector Fonasa falla, la aplicación lo indica y nunca deduce impago.
- Pruebas con OCR real de cifras 11/27, traza por movimiento, bloqueo de 0
  falso positivo y validación del estado del reporte.

## Criterios de aceptación (NO afirmar éxito antes de completar)

| Fase | Prueba | Criterio verificable |
|---|---|---|
| A | Unitarias y OCR local | Todas las pruebas GitHub CI pasan |
| B | PDF original, entorno privado | 5/5 trabajadores, período y días 24/11/27/27/13 |
| C | Streamlit publicado | Encabezado 18.7, SHA lector visible, mismo SHA del PDF |
| D | Streamlit publicado | Diagnóstico de fila muestra recorte correcto, OCR y decisión |
| E | Streamlit publicado | CSV *original* y pantalla muestran los mismos cinco valores |
| F | Robustez sobre documentos distintos | Muestreo de 20 PDF, comparar campos con originales |
| G | Seguridad | 0 cifras inventadas para celdas contradictorias; marcar revisión |
| H | Privacidad | No subir PDF ni datos personales a GitHub o servicios externos |

**Límite:** los criterios C, D y E solo se pueden comprobar en el despliegue
con acceso al enlace / logs o evidencia de ejecución de Streamlit. Una prueba
verde de GitHub no satisface esos criterios.

## Procedimiento en producción

1. Actualizar / reiniciar la app desde Streamlit Community Cloud.
2. Comprobar el encabezado `18.7-Fonasa-trazable` y la huella del lector.
3. Subir el mismo PDF original, pulsar **Analizar documentos**.
4. Abrir `Diagnóstico verificable del OCR de Fonasa`.
5. Comprobar SHA256 del PDF, versión de Tesseract, rotación de página,
   la lectura bruta de filas y el recorte correspondiente a 11 y 27.
6. Si el SHA del archivo difiere, el problema es que se subió otra versión
   del PDF. Si el SHA del lector/version difiere, no se está ejecutando este
   código. Si coinciden pero OCR entrega 2 o None, se dispone de la celda
   exacta y las coordenadas para reproducir la diferencia del servidor.
7. Solo una vez cotejado: habilitar el uso habitual y comparar 20 documentos.

El JSON descargable incluye nombres/RUT; se debe tratar como confidencial y no
adjuntarlo a incidencias públicas.

## Política de precisión

- **OCR reconocido** no significa **dato validado oficialmente**.
- Días 0 o no reconocidos no demuestran no pago.
- Si folio/fecha/período/identidad difieren, mostrar revisión manual y
  conservar la página de origen.
- Nunca prometer 100% de reconocimiento sobre cualquier documento.
- Mantener GALANT en Python + Streamlit, sin migrar a otra plataforma.
