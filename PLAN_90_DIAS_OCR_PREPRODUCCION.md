# GALANT — Ensayo controlado del OCR durante tres meses

**Inicio:** 30 de octubre de 2026 · **cierre programado:** 30 de enero de 2027.

## Estado de esta rama

EXPERIMENTAL · NO fusionar en `main` ni habilitar en la aplicación publicada sin superar los criterios.

**Evidencia del 30/10/2026:** 360 transformaciones de CINCO celdas de días de UNA planilla escaneada real, con verdad manual 24, 11, 27, 27, 13; 185 lecturas numéricas correctas aceptadas; 0 valores incorrectos aceptados; 175 abstenciones. De ellas, 110 eran los casos auditados antes y 250 variantes nuevas generadas con semilla fija 20261030. La precisión sobre valores aceptados es 185/185 en **esa muestra**; la recuperación es 185/360. Estos 360 ensayos no representan 360 comprobantes o trabajadores diferentes.

Antes del control estricto, la misma auditoría registró 71/110 correctos, 25 valores incorrectos y 14 abstenciones. No comparar porcentajes de ambos conjuntos como si fueran archivos independientes.

## Qué hace la prueba experimental

1. **Por defecto no cambia la lectura:** solo se habilita con `GALANT_OCR_STRICT_MODE=1` en un despliegue de PRUEBA.
2. Antes de publicar un número, valida la cantidad de trazos correspondientes a caracteres y pone en revisión casos como `27→2`, `13→3`, `27→11`. Nunca fuerza cero.
3. Guarda en la traza el número OCR **antes del control** y la razón de aceptación/rechazo.
4. No cambia la clasificación de «pago respaldado» por sí mismo: sin lectura o discrepancia implica **revisión**, no impago.
5. CI ejecuta nuevos ensayos de cifras sintéticas y las pruebas previas de Fonasa; el benchmark PRIVADO y MANUAL se ejecuta fuera del repo público.

## Evaluación real con PDF y Excel

**Nunca copiar PDF de trabajadores a GitHub.** Los documentos y el manifest manual deben estar en un equipo/corredor privado. Ejecutar desde la raíz del repo con el entorno Python instalado:

```bash
python -m scripts.validar_corpus_privado --root /ruta/privada/pdfs --manifest /ruta/privada/verdad.json --salida /ruta/privada/resultado.json --min-docs 30
```

El script hace PDF→OCR→nómina→Excel y comprueba cada trabajador por RUT/institución, los días, el período y las pérdidas/duplicados. Exige SHA256 exacto para impedir evaluar un PDF distinto. El JSON de resultado solo contiene contadores agregados, no RUT.

## Criterios de publicación

- Al menos **30 PDF reales distintos, escaneados y anotados manualmente**, con ejemplos de Fonasa, Isapre y otros comprobantes PREVIRED; añadir casos difíciles de baja resolución, rotación y multipágina.
- **0 días incorrectos aceptados, 0 trabajadores omitidos, 0 días pendientes, 0 períodos mal vinculados, 0 instituciones incorrectas** sobre el conjunto de aceptación.
- **0 pagos etiquetados falsamente como acreditados o impagos**; verificar el documento y la fuente oficial según corresponda.
- Ejecutar integración PDF→nómina→Excel contra Streamlit real; pruebas unitarias o GitHub verdes **NO cuentan** como prueba de producción.
- Medir latencia p50/p95, memoria y cantidad de páginas OCR contra la versión 19.1; exigir mejora sin regresión documental.
- Repetir el benchmark diariamente durante el período de 3 meses (se configuró una revisión diaria en ChatGPT que **vigila** CI, no sustituye los ensayos privados).
- Si falta corpus con verdad manual, la promoción queda **BLOQUEADA**; no maquillar como 100% verificado.

## Fuente y privacidad

Repo: https://github.com/Alvarofritzsolis1/proyecto-autmatizacion-002223. Se mantuvo el commit de `main` separado de esta rama. No hay claves, documentos de trabajadores ni RUT reales en este experimento.

**Ningún OCR garantiza exactitud universal para todos los escaneos.** La ingeniería de cumplimiento busca cero errores CRÍTICOS aceptados en el benchmark y revisión explícita de lo demás.
