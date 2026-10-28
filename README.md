# IA actual: chat con Google Gemini (modalidad gratuita)

El asistente interno ahora usa Gemini, no OpenAI. Para instalar la clave sigue [README_GEMINI.md](README_GEMINI.md).

- **Secret**: `GEMINI_API_KEY = "TU_CLAVE"`
- **Modelo inicial**: `GEMINI_MODEL = "gemini-3.5-flash-lite"`
- La clave se guarda solo en **Streamlit App settings → Secrets**, nunca en GitHub.
- El chat usa preguntas parcialmente anonimizadas y métricas generales; no envía PDFs ni nóminas.
- El plan gratuito tiene cuotas y Google puede usar entradas para mejorar productos. No introduzcas datos personales.
- No cambia código, cifras ni estados automáticamente.


---

# Auditoría Laboral de Contratistas

Aplicación en Streamlit para leer planillas de remuneraciones y generar una matriz Excel con estados de auditoría.

## Qué incluye

- Carga simultánea de archivos `.xlsx`, `.xls`, `.csv` y `.pdf`.
- OCR automático en español/inglés para páginas PDF escaneadas, usando Tesseract; intenta recuperar tablas con estrategias de extracción alternativas.
- Detección de cabeceras en las primeras filas y lectura de hojas compatibles de Excel.
- Normalización de RUT, períodos, días, rentas imponibles y mutual.
- Validación de dígito verificador de RUT; los registros dudosos quedan en `REVISAR_DATOS`.
- Alertas para renta imponible positiva con cero días y para diferencias entre bases imponibles.
- Identificación de registros duplicados sin sumarlos automáticamente.
- Revisión del formato de montos: textos inesperados o rentas/días negativos no se convierten silenciosamente en cero para emitir una conformidad.
- Exportación Excel con matriz corporativa, detalle de revisión y log por archivo.
- Prevención de fórmulas y enlaces automáticos en celdas de texto del Excel exportado.
- Límites de carga para reducir el riesgo de agotar la memoria del alojamiento gratuito.
- Tabla de topes opcional por período. No se fijan tasas de cotización ni topes legales en el código.
- Pruebas automatizadas con GitHub Actions ante cada `push` y `pull request`.

## Limitaciones importantes

- El programa **no calcula cotizaciones** ni confirma por sí solo que una cotización fue pagada; verifica valores declarados en los archivos cargados.
- Los importes que no tengan un formato numérico reconocible, así como días o rentas negativos, se marcan para revisión. Los vacíos no se tratan como prueba de un valor real de cero.
- La app intenta OCR automáticamente cuando el PDF está escaneado o no se encuentran tablas. Requiere `packages.txt` con Tesseract y los modelos español/inglés. El OCR no garantiza reconstruir todos los diseños de tabla; si no identifica columnas con seguridad, el archivo se detiene y se solicita exportar a Excel/CSV en vez de generar un resultado parcial. El límite OCR es 60 páginas por PDF.
- Los formatos de Previred varían. Si no se detecta una tabla de forma fiable, el archivo se reporta como error en lugar de asignar columnas por posición aproximada.
- El tope se aplica solo cuando el usuario entrega un CSV con períodos y valores CLP previamente verificados. No se consulta automáticamente una fuente legal externa. Por ejemplo, la Superintendencia de Pensiones informó un tope de 90,0 UF para AFP, salud y ley de accidentes del trabajo desde las remuneraciones de febrero de 2026; el valor en CLP debe verificarse para cada período antes de incluirlo en el CSV ([fuente oficial](https://www71.spensiones.cl/portal/institucional/594/w3-article-16921.html)).
- Si un valor declarado como `renta imponible` supera el tope cargado, el registro se marca `REVISAR_DATOS`, aunque al limitar ambos importes parezcan coincidir. Así se evita que un límite matemático tape una base declarada incorrecta.
- La matriz principal mantiene la estructura solicitada; el motivo de cada alerta o revisión queda en la hoja `Detalle_Revision`.
- Los resultados son un apoyo a la auditoría, no un dictamen legal automático. Revisar los registros marcados y cotejar los documentos originales.

## Despliegue en Streamlit Community Cloud

1. Crea un repositorio nuevo en GitHub.
2. Sube el contenido completo de esta carpeta a la raíz del repositorio. Deben estar en la raíz `app.py`, `auditoria_laboral.py`, `requirements.txt` y `packages.txt`.
3. Entra en [Streamlit Community Cloud](https://share.streamlit.io/) e inicia sesión con GitHub.
4. Pulsa **Create app** y elige el repositorio, la rama (normalmente `main`) y el archivo principal `app.py`.
5. En **Advanced settings**, selecciona una versión estable de Python compatible con las dependencias (por ejemplo, Python 3.12).
6. Pulsa **Deploy**. Streamlit instala también los paquetes del sistema de `packages.txt` para OCR. Si ya existía una app, haz `commit` y `push` con `packages.txt` y las nuevas dependencias; espera a que termine el redeploy y revisa los logs si falla.
7. Al actualizar los archivos y hacer `commit`/`push` a GitHub, Streamlit Community Cloud despliega los cambios automáticamente.
8. **Importante para controlar errores:** GitHub Actions ejecuta pruebas, pero eso por sí solo no bloquea que Streamlit despliegue un `push` directo a `main`. En GitHub, configura una regla de protección de rama para `main` y exige que el trabajo **Pruebas de auditoría laboral / tests** pase antes de permitir integrar cambios. Comprueba el nombre exacto del chequeo en la pestaña **Actions** luego de la primera ejecución.

## Pruebas automáticas

GitHub Actions ejecuta pruebas y comprueba la sintaxis en cada `push` o `pull request`. Para ejecutarlas localmente:

```bash
python -m pip install -r requirements-dev.txt
python -m pytest -q
```

El test de interfaz usa Streamlit AppTest y se omite cuando Streamlit no está instalado en el entorno local.

## Ejecutar localmente

```bash
python -m venv .venv
# Windows PowerShell:
.venv\Scripts\Activate.ps1
# macOS/Linux:
# source .venv/bin/activate
pip install -r requirements.txt
streamlit run app.py
```

## Formato del archivo opcional de topes

El CSV debe tener una fila por período, en CLP:

```csv
periodo_remuneracion,tope_imponible_clp
2026-02,REEMPLAZAR_POR_MONTO_OFICIAL
2026-03,REEMPLAZAR_POR_MONTO_OFICIAL
```

No cargues el texto `REEMPLAZAR_POR_MONTO_OFICIAL`: sustituye cada valor por el monto confirmado para ese período. Si no dispones del tope verificado, no cargues este archivo; el sistema no aplicará la excepción por tope.

## Estados

- `CONFORME`: los datos críticos están presentes, los RUT superan la validación y las bases comparadas cuadran dentro de la tolerancia configurada.
- `ALERTA_DIAS_CERO`: datos críticos válidos, rentas imponibles positivas y días pagados iguales a cero.
- `ALERTA_DESCUADRE_RENTAS`: diferencias entre las bases comparadas superiores a la tolerancia.
- `REVISAR_DATOS`: campos críticos ausentes, RUT inválido, duplicado, valor numérico con formato incorrecto, días fraccionarios/fuera de rango o base imponible superior al tope cargado.

## Privacidad y datos laborales

- **No subas** planillas reales, RUT, liquidaciones, certificados ni documentos de trabajadores al repositorio GitHub. `.gitignore` excluye archivos habituales de datos, pero revisa siempre el área de cambios antes de hacer `commit`.
- El archivo `.gitignore` permite incluir la plantilla `topes_imponibles_plantilla.csv`, pero no los CSV operativos cargados por usuarios.
- Esta app no guarda los documentos en disco de forma permanente por diseño, pero los archivos llegan al entorno remoto de ejecución y se mantienen en memoria durante el procesamiento/sesión. Esto no equivale a procesamiento local.
- Para información laboral real, **mantén el repositorio privado y configura también la app como privada** en Streamlit Community Cloud, con acceso concedido solo a las personas autorizadas. Un repositorio público normalmente produce una app pública por defecto; comprueba los ajustes de privacidad antes de utilizar datos reales.
- La app no implementa autenticación propia, registro de usuarios ni control de permisos por contratista. No debe usarse como sistema multiempresa con datos sensibles sin añadir esos controles.

## Actualización: extractor Previred multipágina

El módulo `previred_pdf.py` corrige el fallo "OCR reconoció texto, pero no se identificaron columnas" para las planillas Previred con estructura como la del ejemplo comprobado. No exige que el PDF sea una sola tabla: reconoce cada anexo por separado y combina trabajadores según RUT con dígito verificador válido.

- **Seguro Social**: recupera la columna `Días Trabajados` después del tipo de jornada (`JC` o `JP`). La renta base de Seguro Social solo se utiliza como control cruzado, no se suma como una cuarta renta.
- **Fonasa/Salud**: identifica `Días Trabajados`, `AFP/IPS` y `Remuneración imponible`, y toma esa sección como fuente primaria de días.
- **AFP**: la primera cifra de cada línea de detalle es `Remuneración imponible`; NO es el monto de `Cotización Obligatoria` ni el `SIS`.
- **ISL/Mutual**: utiliza `Remuneración` del detalle, NO la cotización ni el total a pagar.
- **Totales**: compara bases consolidadas por institución con los montos imponibles declarados en los resúmenes, cuando los resúmenes están presentes.
- **Período**: siempre se prioriza el período dentro del documento. Un archivo llamado `2026-MARZO_FIN_MES` puede contener cotizaciones por remuneraciones de **febrero 2026**, pagadas en marzo.
- **Trazabilidad**: cuando hay PDF se agrega pestaña `Trazabilidad_PDF` con nombre, RUT, período, páginas de respaldo y advertencias.

Si las páginas son imagen, se activa OCR. La lectura de escaneos complejos depende de la calidad y disposición del documento; **no se garantiza** extraer correctamente cualquier PDF. Las fuentes ausentes, errores de RUT, totales descuadrados o necesidad de OCR generan `REVISAR_DATOS` y no `CONFORME`. Por seguridad, no se incluyen PDF reales ni información de trabajadores en este repositorio.

Para comprobar la extracción sin publicar datos personales:

```bash
python -m pip install -r requirements.txt -r requirements-dev.txt
python -m pytest -q
streamlit run app.py
```

Se incluyen pruebas con un comprobante sintético que imita la separación entre Seguro Social, AFP, Salud e ISL. Las pruebas de integración con documentos reales deben realizarse localmente o en un entorno privado autorizado.


## Versión OCR selectivo rápido — comprobante Previred escaneado y girado

Se incorporó `previred_scan_fast.py`, un extractor con dos rutas:

- PDF **digital**: PyMuPDF y extractor Previred con texto original, sin Tesseract.
- PDF **escaneado** con retículas Previred reconocibles: PyMuPDF renderiza a escala
  moderada, reconoce la orientación, detecta límites geométricos y ejecuta OCR
  exclusivamente sobre RUT, nombre, días declarados y renta imponible de los
  anexos relevantes. **Ignora portadas, firma, glosas legales, tasas y montos de
  cotización que no son la base imponible**. Los datos se agrupan por RUT válido
  y se confrontan entre Salud, AFP y la entidad de accidentes.
- Si hay dudas de lectura, se vuelve a pasar OCR **solo en las celdas ambiguas**
  y se comparan lecturas alternativas de esa misma celda con las otras fuentes.
  Cuando una fuente tiene un RUT borroso se puede recuperar por el orden de la
  tabla **solo** cuando hay tres o más coincidencias verificadas por RUT y el
  número de filas es idéntico; la operación se registra como revisión.
- Para escaneos no compatibles se conserva la ruta genérica, que puede ser más
  lenta y exigir una configuración adaptada. No es reconocimiento universal.

Se comprobó localmente con un PDF real **de 12 páginas escaneadas y giradas**,
que contiene ocho trabajadores. El lector recuperó 8 trabajadores, período
`2026-04`, 51 días declarados en total, mutual ACHS, y renta imponible total
**$916.299 por cada una de las fuentes Salud, AFP y Mutual**. Al ejecutar el
pipeline completo, el resultado lleva `REVISAR_DATOS`, porque incluye OCR
inferencial y se requiere cotejar la fuente original antes de aprobar.

**Rendimiento:** prueba local de referencia: aproximadamente 11 segundos en un
archivo de 12 páginas. No se garantiza un tiempo fijo en Streamlit Cloud ni
para documentos con cientos de trabajadores; depende del hardware, resolución,
calidad y cantidad de celdas dudosas. El sistema conserva el rendimiento
lineal sobre los anexos y evita OCR en portadas sin datos individuales.

El PDF real no se incluye en el proyecto ni en el repositorio GitHub. Solo se
incluyen pruebas con datos inventados y configuración de producción.
