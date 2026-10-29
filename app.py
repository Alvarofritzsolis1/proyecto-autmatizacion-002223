"""GALANT · Control documental de contratistas (Streamlit)."""
from __future__ import annotations

import hashlib
import json
import os
# Tesseract invoca subprocess por celda; cuatro hilos POR llamada ralentizan
# un servidor pequeño cuando hay varios PDF. Límite recomendado por Tesseract.
os.environ.setdefault("OMP_THREAD_LIMIT", "1")
import platform
import sys
from pathlib import Path

import cv2
import pytesseract
import fitz
from concurrent.futures import ThreadPoolExecutor, as_completed
import time
import pandas as pd
import streamlit as st

from auditoria_laboral import COLUMNAS_SALIDA, ejecutar_pipeline, plantilla_topes_csv
from cruce_documental_galant import conciliar_f301_previred
from f301_lector import analizar_f301, es_f301
from bandeja_revision import generar_bandeja, resumen_calidad
from informe_galant import informe_consolidado
from pago_documental import analizar_pago_pdf
from fonasa_runtime import extraer_fonasa_con_contrato, estado_lector_fonasa
from fonasa_validacion import comprobar_traza_dias
from nomina_salud import construir_nomina_salud
from reporte_nomina_excel import generar_excel_nomina

VERSION = "19.1-Rescate-de-Planillas"
MAX_ARCHIVOS = 20
MAX_BYTES_TOTAL = 60 * 1024 * 1024

st.set_page_config(
    page_title="GALANT | Control Documental",
    page_icon="🛡️",
    layout="wide",
    initial_sidebar_state="collapsed",
)
st.title("GALANT")
def _estado_motor():
    """Incluye huella del BYTECODE activo, no solo código fuente en disco."""
    try:
        return estado_lector_fonasa()
    except (OSError, ImportError, RuntimeError, AttributeError) as exc:
        return {
            "contrato_traza": False,
            "error": f"{type(exc).__name__}: {str(exc)[:200]}",
        }


def _huella_motor():
    estado = _estado_motor()
    return (
        estado.get("sha256_fuente_16", "sin-fuente") + ":"
        + estado.get("sha256_codigo_activo_16", "sin-modulo")
    )


def _version_tesseract():
    try:
        return str(pytesseract.get_tesseract_version())
    except (RuntimeError, OSError, pytesseract.TesseractNotFoundError):
        # La ausencia de Tesseract debe mostrarse como fallo de entorno,
        # sin hacer que Streamlit se caiga antes de mostrar el diagnóstico.
        return "NO DISPONIBLE"

estado_motor = _estado_motor()
st.caption(
    f"Control documental de contratistas · {VERSION} "
    f"· fuente/código en memoria {_huella_motor()}"
)
if not estado_motor.get("contrato_traza"):
    st.error(
        "El lector Fonasa cargado no corresponde al módulo actualizado. "
        "No se considerarán válidas lecturas sin trazabilidad. "
        + estado_motor.get("error", "")
    )
st.info("**Modo rápido activo:** búsqueda de planillas Fonasa e Isapre con rescate automático si falla la lectura inicial. Se omiten cuadraturas de montos por defecto.")
st.write("Sube tus documentos y presiona **Analizar documentos**.")

st.subheader("Subir archivos")
archivos_subidos = st.file_uploader(
    "PDF, Excel o CSV de F30-1 y cotizaciones",
    type=["pdf", "xlsx", "xls", "csv"],
    accept_multiple_files=True,
    max_upload_size=25,
    help=f"Hasta {MAX_ARCHIVOS} archivos y 60 MB en total. Los PDF escaneados usan OCR.",
)
archivos = list(archivos_subidos or [])
limite_excedido = len(archivos) > MAX_ARCHIVOS or sum(a.size for a in archivos) > MAX_BYTES_TOTAL
if limite_excedido:
    st.error("Se excedió el máximo de 20 archivos o 60 MB. Divide la carga.")

with st.expander("Configuración opcional", expanded=False):
    modo_avanzado = st.checkbox(
        "Auditoría avanzada de montos y bases imponibles (no necesaria para verificar respaldo de pago)",
        value=False,
        help="La revisión rápida de respaldo de pago, fecha y período funciona sin extraer toda la nómina.",
    )
    lectura_ampliada = st.checkbox(
        "Ampliar la búsqueda en escaneos con muchas instituciones",
        value=False,
        help="Lee hasta 20 páginas candidatas por PDF. Aumenta la cobertura, pero tarda más.",
    )
    usar_rapidocr = st.checkbox(
        "OCR de rescate mejorado (RapidOCR, gratuito)",
        value=True,
        help=(
            "Usa un segundo OCR local solo en páginas escaneadas con datos de "
            "pago, fecha, período o folio incompletos. No sube PDF a otro servicio. "
            "Puede aumentar el tiempo por documento."
        ),
    )
    a, b = st.columns(2)
    with a:
        tolerancia = st.number_input(
            "Tolerancia al comparar bases imponibles (CLP)",
            min_value=0, max_value=100000, value=15, step=5,
            help="Margen de diferencia de bases, no una tasa de cotización."
        )
    with b:
        incluir_mutual = st.checkbox(
            "Comparar base imponible de Mutual/ISL", value=True,
            help="Si se desactiva, el análisis de Mutual se reduce; no acredita cumplimiento."
        )
    st.download_button(
        "Plantilla opcional de topes imponibles",
        data=plantilla_topes_csv(), file_name="topes_imponibles_plantilla.csv",
        mime="text/csv"
    )
    topes_subido = st.file_uploader(
        "Topes oficiales verificados por período (CSV opcional)",
        type=["csv"], key="galant_topes_csv", max_upload_size=2,
    )
    if topes_subido is not None and topes_subido.size > 2*1024*1024:
        limite_excedido = True
        st.error("El CSV de topes no puede superar 2 MB.")

def _firma_actual():
    h = hashlib.sha256()
    # La versión del motor FORMA PARTE de la huella. Si la app se actualiza
    # conservando la sesión, un reporte anterior no puede mostrarse como nuevo.
    h.update(VERSION.encode("utf-8"))
    h.update(_huella_motor().encode("ascii"))
    for archivo in archivos:
        h.update(archivo.name.encode("utf-8", errors="replace"))
        h.update(archivo.getvalue())
    if topes_subido:
        h.update(topes_subido.getvalue())
    h.update(str(int(tolerancia)).encode())
    h.update(str(bool(incluir_mutual)).encode())
    h.update(str(bool(modo_avanzado)).encode())
    h.update(str(bool(lectura_ampliada)).encode())
    h.update(str(bool(usar_rapidocr)).encode())
    return h.hexdigest()

if st.button(
    "Analizar documentos", type="primary", disabled=not archivos or limite_excedido,
):
    st.session_state.pop("reporte_galant", None)
    # Cada clic es una solicitud explícita de REANÁLISIS. No reutilizar
    # una nómina Fonasa incorrecta del caché de la misma sesión.
    st.session_state.pop("galant_cache_pago", None)
    inicio = time.perf_counter()
    firma = _firma_actual()
    entradas = []
    duplicados = []
    huellas = {}
    for archivo in archivos:
        data = archivo.getvalue()
        clave = hashlib.sha256(data).hexdigest()
        if clave in huellas:
            duplicados.append((archivo.name, huellas[clave]))
        else:
            huellas[clave] = archivo.name
            entradas.append((data, archivo.name))

    certificados, nomina, incidencias = [], [], []
    matriz = pd.DataFrame(columns=COLUMNAS_SALIDA)
    excel, detalle, log = None, pd.DataFrame(), pd.DataFrame()
    errores = []
    pagos_documentales = []
    nominas_fonasa = []
    pruebas_ejecucion = []
    tiempos_pagos = []
    cache_sesion = st.session_state.setdefault("galant_cache_pago", {})
    with st.spinner("Leyendo documentos y conciliando sus respaldos..."):
        f301, previred = [], []
        for data, nombre in entradas:
            if nombre.lower().endswith(".pdf") and es_f301(data, nombre):
                f301.append((data, nombre))
            else:
                previred.append((data, nombre))
        # El OCR se procesa concurrentemente por PDF (nunca una misma página
        # desde varios hilos). La memoria de sesión se consulta SOLO en el hilo
        # principal, para evitar condiciones de carrera en Streamlit.
        def _leer_pago_trabajo(data, nombre):
            t = time.perf_counter()
            resultado = analizar_pago_pdf(
                data, nombre,
                max_paginas_ocr=20 if lectura_ampliada else 6,
                usar_rapidocr=usar_rapidocr,
                max_paginas_rapidocr=3 if lectura_ampliada else 2,
            )
            # Extraer nombres/RUT/días del anexo Fonasa sin cuadre de montos.
            # Primero páginas asociadas al comprobante, no todas las páginas.
            paginas = [
                e.get("pagina") for e in resultado.get("comprobantes", [])
                if str(e.get("institucion", "")).lower() == "fonasa"
                or str(e.get("institucion", "")).lower().startswith("isapre")
            ]
            if not paginas:
                # Anexos suelen seguir a la carátula; búsqueda acotada.
                paginas = list(range(2, min(resultado["paginas"], 12) + 1, 2))
            try:
                diagnostico_lector = {}
                instituciones_salud = {
                    int(e.get("pagina")): e.get("institucion", "")
                    for e in resultado.get("comprobantes", [])
                    if isinstance(e.get("pagina"), int)
                    and (
                        e.get("institucion") == "Fonasa"
                        or str(e.get("institucion", "")).startswith("Isapre")
                    )
                }
                nomina = extraer_fonasa_con_contrato(
                    data, paginas_candidatas=paginas,
                    instituciones_candidatas=instituciones_salud,
                    diagnostico=diagnostico_lector,
                    usar_ocr_alternativo=usar_rapidocr,
                )
                resultado["diagnostico_nomina"] = diagnostico_lector
            except Exception as exc:
                # Un fallo de extracción de nómina NO equivale a impago.
                # Informar el tipo de error y conservar los recibos obtenidos.
                resultado["error_lector_fonasa"] = (
                    f"{type(exc).__name__}: {str(exc)[:250]}"
                )
                resultado["diagnostico_nomina"] = {
                    **locals().get("diagnostico_lector", {}),
                    "error": type(exc).__name__,
                }
                nomina = []
            return resultado, time.perf_counter() - t, nomina

        recibos_ordenados = {}
        pdfs_pago = [
            (i, data, nombre) for i, (data, nombre) in enumerate(previred)
            if nombre.lower().endswith(".pdf")
        ]
        with ThreadPoolExecutor(max_workers=min(2, max(1, len(pdfs_pago)))) as grupo:
            trabajos = {}
            for i, data, nombre in pdfs_pago:
                clave_cache = (
                    VERSION + ":" + hashlib.sha256(data).hexdigest()
                    + ":" + str(lectura_ampliada)
                    + ":" + str(usar_rapidocr)
                )
                if clave_cache in cache_sesion:
                    recibos_ordenados[i] = (
                        dict(cache_sesion[clave_cache]), nombre, 0.0, True
                    )
                    continue
                futuro = grupo.submit(_leer_pago_trabajo, data, nombre)
                trabajos[futuro] = (i, clave_cache, nombre)

            for futuro in as_completed(trabajos):
                i, clave_cache, nombre = trabajos[futuro]
                try:
                    evidencia, segundos, nomina = futuro.result()
                    evidencia = dict(evidencia)
                    evidencia["nomina_fonasa"] = nomina
                    cache_sesion[clave_cache] = dict(evidencia)
                    # Máximo 50 resultados en la sesión privada, sin caché global.
                    if len(cache_sesion) > 50:
                        cache_sesion.pop(next(iter(cache_sesion)))
                    recibos_ordenados[i] = (evidencia, nombre, segundos, False)
                except Exception as exc:
                    errores.append(
                        "Lectura de pago: " + nombre + ": " + str(exc)[:250]
                    )
        for i in sorted(recibos_ordenados):
            evidencia, nombre, segundos, reutilizado = recibos_ordenados[i]
            evidencia = dict(evidencia)
            evidencia["archivo"] = nombre
            # Este identificador permite comprobar si la app recibió
            # los MISMOS bytes que se evaluaron fuera de Streamlit.
            archivo_original = next(
                (data for data, n in entradas if n == nombre), None
            )
            evidencia["sha256_pdf"] = (
                hashlib.sha256(archivo_original).hexdigest()
                if archivo_original is not None else ""
            )
            pagos_documentales.append(evidencia)
            for anexo in evidencia.get("nomina_fonasa", []):
                for fila in anexo.get("trabajadores", []):
                    nominas_fonasa.append({
                        **fila,
                        "archivo": nombre,
                        "pagina_fonasa": anexo["pagina"],
                        "rotacion_fonasa": anexo.get("rotacion"),
                        "institucion_salud": anexo.get(
                            "institucion_salud",
                            fila.get("institucion_salud",
                                     "Salud (institución por confirmar)")
                        ),
                    })
            tiempos_pagos.append({
                "Archivo": nombre,
                "Segundos": round(segundos, 2),
                "Páginas": evidencia["paginas"],
                "Páginas con OCR": evidencia["paginas_ocr"],
                "Páginas rescate RapidOCR": len(
                    evidencia.get("rapidocr", {}).get("paginas", [])
                ),
                "Rescate RapidOCR": evidencia.get("rapidocr", {}).get(
                    "estado", "deshabilitado"
                ),
                "Trabajadores salud": sum(
                    len(x.get("trabajadores", []))
                    for x in evidencia.get("nomina_fonasa", [])
                ),
                "Ruta lectura nómina": evidencia.get(
                    "diagnostico_nomina", {}
                ).get("ruta", "sin resultado"),
                "Tiempo nómina (s)": evidencia.get(
                    "diagnostico_nomina", {}
                ).get("duracion_segundos"),
                "Comprobantes detectados": len(evidencia["comprobantes"]),
                "Comprobantes completos": sum(
                    bool(x.get("periodo") and x.get("fecha_pago"))
                    for x in evidencia["comprobantes"]
                ),
                "Caché": "Reutilizado" if reutilizado else "Analizado",
            })
        if f301:
            certificados, nomina, incidencias = analizar_f301(f301)
        if previred and modo_avanzado:
            try:
                matriz, excel, detalle, log = ejecutar_pipeline(
                    previred,
                    topes_csv=topes_subido.getvalue() if topes_subido else None,
                    nombre_topes=topes_subido.name if topes_subido else "topes.csv",
                    tolerancia_clp=int(tolerancia),
                    incluir_mutual=incluir_mutual,
                )
            except Exception as exc:
                errores.append("Cotizaciones/planillas: " + str(exc)[:450])
        if certificados or modo_avanzado:
            cruzados, resumen_cruce = conciliar_f301_previred(
                certificados, nomina, matriz
            )
        else:
            cruzados, resumen_cruce = pd.DataFrame(), pd.DataFrame()
        bandeja = generar_bandeja(
            certificados=certificados, incidencias=incidencias,
            detalle=detalle, log=log, cruce_detalle=cruzados,
            cruce_resumen=resumen_cruce, errores=errores, duplicados=duplicados,
            pagos_documentales=pagos_documentales,
        )
        calidad = (
            resumen_calidad(certificados, matriz, bandeja)
            if (certificados or modo_avanzado) else {}
        )
        # Se omite generar otro Excel costoso de conciliación cuando el
        # usuario solo quiere la nómina de trabajadores y días cotizados.
        reporte_excel = None
        if certificados or modo_avanzado:
            try:
                reporte_excel = informe_consolidado(
                    bandeja=bandeja, certificados=certificados, matriz=matriz,
                    detalle_cruce=cruzados, resumen_cruce=resumen_cruce,
                    log=log, incidencias=incidencias,
                )
            except Exception:
                pass  # No perder la nómina por un fallo secundario.
    # Consolidar una sola nómina de trabajadores de FONASA E ISAPRES.
    # Solo asociar un pago con una planilla de la misma institución de salud.
    nomina_unificada, alertas_salud = construir_nomina_salud(
        pagos_documentales, nominas_fonasa
    )
    st.session_state["reporte_galant"] = {
        "firma": firma, "engine_release": VERSION,
        "certificados": certificados,
        "nomina": nomina, "incidencias": incidencias,
        "matriz": matriz, "excel": excel, "detalle": detalle, "log": log,
        "cruce_detalle": cruzados, "cruce_resumen": resumen_cruce,
        "bandeja": bandeja, "calidad": calidad, "reporte_excel": reporte_excel,
        "duplicados": duplicados, "errores": errores,
        "pagos_documentales": pagos_documentales,
        "nominas_fonasa": nominas_fonasa,
        "nomina_unificada": nomina_unificada,
        "alertas_salud": alertas_salud,
        "entorno": {
            "release": VERSION,
            "codigo_lector_sha256_16": _huella_motor(),
            "lector_cargado": _estado_motor(),
            "python": sys.version.split()[0],
            "sistema": platform.system(),
            "opencv": cv2.__version__,
            "tesseract": _version_tesseract(),
            "streamlit": st.__version__,
        },
        "tiempos_pagos": tiempos_pagos,
        "duracion": time.perf_counter()-inicio,
    }

reporte = st.session_state.get("reporte_galant")
if reporte and reporte.get("engine_release") != VERSION:
    # Streamlit puede preservar session_state y st.data_editor después de
    # desplegar otro commit. Invalidar el informe antes de mostrar cualquier
    # resultado antiguo: nunca presentar 2/None como si fuera OCR 18.6.2.
    st.session_state.pop("reporte_galant", None)
    st.warning(
        "GALANT actualizó su lector de días Fonasa. "
        "El informe anterior se descartó. Presiona «Analizar documentos» "
        "para recalcular los valores con esta versión."
    )
    reporte = None
if reporte and (not archivos or reporte["firma"] != _firma_actual()):
    st.info("Cambiaste los archivos. Presiona «Analizar documentos» para actualizar.")
elif reporte:
    st.subheader("Resultado")
    matriz = reporte["matriz"]
    certificados = reporte["certificados"]
    pendientes = reporte["bandeja"]

    # Un RUT se cuenta una sola vez aunque figure en F30-1 y cotizaciones.
    ruts = set()
    if "trabajador_rut" in matriz.columns:
        ruts.update(str(x).strip() for x in matriz["trabajador_rut"].dropna())
    for trabajador in reporte["nomina"]:
        rut = str(trabajador.get("trabajador_rut") or "").strip()
        if rut:
            ruts.add(rut)
    ruts = {rut for rut in ruts if rut.lower() not in {"", "nan", "none"}}
    archivos_leidos = len(certificados)
    archivos_leidos += sum(bool(doc["comprobantes"]) for doc in reporte.get("pagos_documentales", []))
    if reporte["log"] is not None and not reporte["log"].empty:
        archivos_leidos += int(
            reporte["log"]["resultado"].eq("PROCESADO").sum()
        )

    m1, m2, m3 = st.columns(3)
    m1.metric("Archivos leídos", archivos_leidos)
    m2.metric("Trabajadores identificados", len(ruts))
    m3.metric("Observaciones", len(pendientes))

    if reporte["errores"]:
        st.error("Uno o más archivos no pudieron leerse.")
        with st.expander("Ver el motivo del error"):
            for error in reporte["errores"]:
                st.write(error)
    if reporte["duplicados"]:
        st.info("Se omitieron archivos repetidos para evitar contar dos veces.")

    st.caption(f"Duración total del análisis: {reporte['duracion']:.2f} segundos. "
               "La duración depende del servidor y del tamaño de los documentos.")
    with st.expander("Rendimiento por archivo: tiempos y cobertura"):
        tiempos = reporte.get("tiempos_pagos", [])
        if tiempos:
            st.dataframe(pd.DataFrame(tiempos), hide_index=True, use_container_width=True)
    st.markdown("#### Trabajadores y días cotizados")
    st.caption(
        "Incluye planillas de Fonasa e Isapres. Se informa el número de días "
        "declarados y el respaldo de pago correspondiente a la MISMA institución. "
        "No se realizan cuadraturas obligatorias de montos."
    )
    registros_salud = reporte.get("nomina_unificada", [])
    filas_fonasa = [
        {
            "Archivo": reg.get("archivo", ""),
            "Nombre trabajador": reg.get("nombre", ""),
            "RUT": reg.get("rut", ""),
            "Sistema salud": reg.get("sistema", "Por verificar"),
            "Institución": reg.get("institucion_salud", ""),
            "Días trabajados": reg.get("dias"),
            "Período": reg.get("periodo") or "Por confirmar",
            "Fecha de pago": reg.get("fecha_pago") or "Por confirmar",
            "Folio": reg.get("folio") or "Por confirmar",
            "Situación": reg.get("situacion", "Revisar"),
            "Página planilla": reg.get("pagina_planilla"),
            "Estado OCR días": reg.get("metodo_lectura", "Sin traza"),
            "Método OCR": reg.get("metodo_lectura", ""),
            "Observación": reg.get("observacion", ""),
        }
        for reg in registros_salud
    ]
    if reporte.get("alertas_salud"):
        st.warning(
            "Hay documentos o instituciones de salud cuya nómina no pudo "
            "identificarse con seguridad. Consulta la hoja Revisar del Excel: "
            "no se deben omitir silenciosamente estos trabajadores."
        )
    if filas_fonasa:
        c1, c2, c3 = st.columns(3)
        c1.metric("Trabajadores y períodos", len(filas_fonasa))
        c2.metric(
            "Con días identificados",
            sum(x["Días trabajados"] is not None for x in filas_fonasa)
        )
        c3.metric(
            "Respaldo documental de pago",
            sum(x["Situación"] == "Pago respaldado en PDF"
                for x in filas_fonasa)
        )
        st.download_button(
            "Descargar Excel de trabajadores y días cotizados",
            data=generar_excel_nomina(
                registros_salud, reporte.get("alertas_salud", [])
            ),
            file_name="GALANT_Trabajadores_Dias_Cotizados.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            type="primary",
            use_container_width=True,
        )
    if filas_fonasa:
        cantidad_sin_traza = sum(
            x["Estado OCR días"] == "SIN_TRAZA" for x in filas_fonasa
        )
        if cantidad_sin_traza:
            st.error(
                f"{cantidad_sin_traza} trabajador(es) sin traza del módulo "
                "OCR. Es una FALLA DEL LECTOR EN MEMORIA, no una prueba "
                "de días no trabajados. Reiniciar Streamlit y revisar "
                "diagnóstico de fuente/código en memoria."
            )
        tabla_fonasa = pd.DataFrame(filas_fonasa)
        # Columnas numéricas con valores anulables: no mostrar la palabra
        # "None" como si fuera un resultado de los días del trabajador.
        tabla_fonasa["Días trabajados"] = pd.to_numeric(
            tabla_fonasa["Días trabajados"], errors="coerce"
        ).astype("Int64")
        # La tabla principal es SOLO OCR, no mezcla correcciones anteriores.
        st.dataframe(
            tabla_fonasa, hide_index=True, use_container_width=True
        )
        st.download_button(
            "Descargar lectura OCR de salud (CSV)",
            data=tabla_fonasa.to_csv(index=False).encode("utf-8-sig"),
            file_name="GALANT_Nomina_Salud_lectura_original.csv",
            mime="text/csv",
        )
        # Las correcciones humanas tienen su propio editor y exportación.
        with st.expander("Corregir manualmente días cotejados con el PDF"):
            st.caption(
                "Esta tabla NO modifica el resultado original del OCR. "
                "Solo exporta correcciones humanas, identificadas como tales."
            )
            tabla_editada = st.data_editor(
                tabla_fonasa,
                hide_index=True, use_container_width=True,
                num_rows="fixed",
                disabled=[
                    c for c in tabla_fonasa.columns if c != "Días trabajados"
                ],
                column_config={
                    "Días trabajados": st.column_config.NumberColumn(
                        "Días trabajados", min_value=0, max_value=31, step=1
                    ),
                },
                key="edicion_manual_" + VERSION + "_" + reporte["firma"][:12],
            )
            antes = pd.to_numeric(
                tabla_fonasa["Días trabajados"], errors="coerce"
            )
            despues = pd.to_numeric(
                tabla_editada["Días trabajados"], errors="coerce"
            )
            correcciones = ~(
                antes.eq(despues) | (antes.isna() & despues.isna())
            )
            if bool(correcciones.fillna(False).any()):
                tabla_editada.loc[
                    correcciones.fillna(False), "Observación"
                ] = "Corregido manualmente contra PDF"
                st.warning(
                    f"{int(correcciones.fillna(False).sum())} corrección(es) "
                    "humanas; no corresponden a la salida del OCR."
                )
            st.download_button(
                "Descargar nómina con correcciones manuales (CSV)",
                data=tabla_editada.to_csv(index=False).encode("utf-8-sig"),
                file_name="GALANT_Nomina_Salud_correcciones_manuales.csv",
                mime="text/csv",
            )
        with st.expander("Diagnóstico verificable del OCR de salud", expanded=False):
            st.warning(
                "El diagnóstico puede contener RUT y nombres de trabajadores. "
                "No lo compartas públicamente."
            )
            st.json(reporte.get("entorno", {}))
            trazas = []
            for reg in reporte.get("nominas_fonasa", []):
                for celda in reg.get("traza_dias", []):
                    trazas.append({
                        "Archivo": reg.get("archivo", ""),
                        "Página": reg.get("pagina_fonasa"),
                        "Rotación": reg.get("rotacion_fonasa"),
                        "Trabajador": reg.get("trabajador_nombre"),
                        "RUT": reg.get("trabajador_rut"),
                        "Fila": celda.get("fila"),
                        "OCR bruto": celda.get("ocr_bruto", "(sin dato)"),
                        "Doble trazo 11": celda.get("dos_trazos", False),
                        "Glifo cerrado": celda.get("glifo_cerrado", False),
                        "Valor elegido": celda.get("valor"),
                        "Regla": celda.get("metodo", "sin_regla"),
                        "Recorte px": celda.get("celda_px"),
                    })
            if trazas:
                st.dataframe(
                    pd.DataFrame(trazas),
                    hide_index=True, use_container_width=True,
                )
            else:
                st.error(
                    "El OCR no entregó trazabilidad de celdas. No afirmar "
                    "que los días quedaron verificados."
                )
            pruebas = [
                {
                    "archivo": doc.get("archivo"),
                    "sha256_pdf": doc.get("sha256_pdf"),
                    "paginas": doc.get("paginas"),
                    "paginas_ocr": doc.get("paginas_ocr"),
                    "error_lector_fonasa": doc.get("error_lector_fonasa"),
                    "fonasa_paginas": [
                        {
                            "pagina": x.get("pagina"),
                            "rotacion": x.get("rotacion"),
                            "trabajadores": len(x.get("trabajadores", [])),
                        } for x in doc.get("nomina_fonasa", [])
                    ],
                }
                for doc in reporte.get("pagos_documentales", [])
            ]
            st.dataframe(
                pd.DataFrame(pruebas), hide_index=True, use_container_width=True
            )
            fallidos = [
                d for d in pruebas if d.get("error_lector_fonasa")
            ]
            if fallidos:
                st.error(
                    f"El lector Fonasa falló internamente en "
                    f"{len(fallidos)} documento(s); no afirmar que se "
                    "completó su nómina. Ver columna error_lector_fonasa."
                )
            paquete = {
                "entorno": reporte.get("entorno", {}),
                "documentos": pruebas,
                "trazas": trazas,
            }
            st.download_button(
                "Descargar diagnóstico completo (JSON privado)",
                data=json.dumps(
                    paquete, ensure_ascii=False, indent=2,
                    default=str
                ).encode("utf-8"),
                file_name="GALANT_Diagnostico_Salud_Privado.json",
                mime="application/json",
            )
            if trazas:
                opciones = [
                    (j, reg)
                    for j, reg in enumerate(reporte.get("nominas_fonasa", []))
                    if reg.get("traza_dias")
                ]
                elegido = st.selectbox(
                    "Ver recorte original de los días (comprobación visual)",
                    options=range(len(opciones)),
                    format_func=lambda k: (
                        opciones[k][1].get("trabajador_nombre", "Trabajador")
                        + " · pág. "
                        + str(opciones[k][1].get("pagina_fonasa"))
                    ),
                    key="visualizacion_dias_" + VERSION,
                )
                fila = opciones[elegido][1]
                pdf_cargado = next(
                    (u.getvalue() for u in archivos
                     if u.name == fila.get("archivo")), None
                )
                traza_primaria = next(
                    (x for x in fila.get("traza_dias", [])
                     if x.get("valor") is not None and x.get("celda_px")),
                    None,
                ) or next(
                    (x for x in fila.get("traza_dias", [])
                     if x.get("celda_px")), None
                )
                if pdf_cargado and traza_primaria:
                    try:
                        with fitz.open(
                            stream=pdf_cargado, filetype="pdf"
                        ) as doc:
                            pix = doc[fila["pagina_fonasa"] - 1].get_pixmap(
                                matrix=fitz.Matrix(3, 3),
                                colorspace=fitz.csGRAY, alpha=False,
                            )
                            from PIL import Image
                            im = Image.frombytes(
                                "L", (pix.width, pix.height), pix.samples
                            )
                            rot = fila.get("rotacion_fonasa") or 0
                            if rot:
                                im = im.rotate(rot, expand=True)
                            x0, y0, x1, y1 = traza_primaria["celda_px"]
                            margen = 30
                            muestra = im.crop((
                                max(0, x0 - margen),
                                max(0, y0 - margen),
                                min(im.width, x1 + margen),
                                min(im.height, y1 + margen),
                            ))
                            st.image(
                                muestra, width=320,
                                caption="Recorte real en el servidor Streamlit",
                            )
                    except Exception:
                        st.warning(
                            "No se pudo renderizar la celda. Consultar "
                            "el PDF original o descargar el diagnóstico."
                        )
        ambiguos = sum(x.get("dias_requieren_revision", False)
                       for x in reporte.get("nominas_fonasa", []))
        if ambiguos:
            st.info(
                f"{ambiguos} registro(s) con días difíciles de reconocer; "
                "revisar el anexo original. No equivale a cotizaciones impagas."
            )
    else:
        st.info(
            "No se pudo recuperar una nómina de trabajadores de Fonasa o Isapre. "
            "Revisa la calidad del documento y los avisos anteriores; "
            "esto no significa que las cotizaciones estén impagas."
        )
    st.markdown("#### Revisiones pendientes")
    if pendientes.empty:
        if reporte["errores"] or archivos_leidos == 0:
            st.warning(
                "No hay resultados suficientes. Revisa los archivos que no se pudieron leer."
            )
        elif modo_avanzado:
            st.info(
                "Sin observaciones en las revisiones seleccionadas. "
                "Esto no equivale a certificación oficial de pago."
            )
        else:
            st.info(
                "La revisión principal muestra días cotizados y respaldo "
                "por trabajador; el análisis de montos es opcional."
            )
    else:
        columnas = {
            "archivo": "Archivo",
            "rut_trabajador": "RUT trabajador",
            "hallazgo": "Qué revisar",
            "accion_recomendada": "Qué hacer",
        }
        categorias_avanzadas = {
            "Cotizaciones", "Cobertura OCR (avanzado)",
            "Cruce F30-1/Previred", "Auditoría avanzada",
        }
        es_avanzado = pendientes["categoria"].isin(categorias_avanzadas)
        avisos_pago = pendientes.loc[~es_avanzado]
        avisos_avanzados = pendientes.loc[es_avanzado]

        if not avisos_pago.empty:
            st.markdown("**Documentos y acreditación de pago**")
            st.dataframe(
                avisos_pago.reindex(columns=list(columnas)).rename(columns=columnas),
                hide_index=True, use_container_width=True,
            )
        if not avisos_avanzados.empty:
            with st.expander(
                f"Auditoría avanzada de nóminas, bases y OCR ({len(avisos_avanzados)} observaciones)",
                expanded=False,
            ):
                st.info(
                    "Estas observaciones son de lectura o cuadratura de nóminas. "
                    "No indican por sí solas que las cotizaciones estén impagas. "
                    "Revisar por separado los comprobantes de pago."
                )
                st.dataframe(
                    avisos_avanzados.reindex(columns=list(columnas)).rename(
                        columns=columnas
                    ),
                    hide_index=True, use_container_width=True,
                )
        if avisos_pago.empty:
            st.caption(
                "No hay observaciones adicionales de documentos o pago en esta bandeja. "
                "Comprueba la situación y respaldo por trabajador en la nómina superior."
            )

    if reporte.get("reporte_excel"):
        st.download_button(
            "Descargar informe Excel",
            data=reporte["reporte_excel"],
            file_name="GALANT_Informe_Documental.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            type="primary",
        )

    with st.expander("Ver documentos y trabajadores"):
        if not matriz.empty:
            st.markdown("**Cotizaciones**")
            columnas_cot = {
                "trabajador_nombre": "Trabajador",
                "trabajador_rut": "RUT",
                "periodo_remuneracion": "Período",
                "dias_reales_pagados": "Días",
                "renta_imponible_afp": "Base AFP",
                "renta_imponible_salud": "Base salud",
                "estado_auditoria": "Resultado",
            }
            st.dataframe(
                matriz.reindex(columns=list(columnas_cot)).rename(
                    columns=columnas_cot
                ),
                hide_index=True, use_container_width=True,
            )
        if certificados:
            st.markdown("**Certificados F30-1**")
            filas_f301 = []
            for cert in certificados:
                declarados = cert.get("trabajadores_declarados")
                filas_f301.append({
                    "Empresa": cert.get("contratista") or "Sin identificar",
                    "Período": cert.get("periodo") or "Sin identificar",
                    "Trabajadores": cert.get("trabajadores_identificados", 0),
                    "Declarados": declarados if declarados is not None else "Sin identificar",
                    "Estado": (
                        "Pago declarado, no verificado"
                        if cert.get("cotizaciones") == "SI_DECLARADO_EN_PDF"
                        else "Requiere revisión"
                    ),
                })
            st.dataframe(
                pd.DataFrame(filas_f301), hide_index=True, use_container_width=True
            )
            st.link_button(
                "Consultar certificado en la DT",
                "https://verificador.dirtrab.cl/",
            )
        resumen_cruce = reporte["cruce_resumen"]
        if resumen_cruce is not None and not resumen_cruce.empty:
            st.markdown("**Comparación F30-1 y cotizaciones**")
            columnas_cruce = {
                "contratista": "Empresa",
                "periodo": "Período",
                "trabajadores_declarados": "Declarados",
                "rut_coincidentes": "Coinciden",
                "rut_pendientes": "Pendientes",
                "resultado": "Resultado",
            }
            st.dataframe(
                resumen_cruce.reindex(columns=list(columnas_cruce)).rename(
                    columns=columnas_cruce
                ),
                hide_index=True, use_container_width=True,
            )
        if matriz.empty and not certificados:
            st.info("No se recuperaron datos de trabajadores.")

    st.caption(
        f"GALANT v{VERSION} · La revisión compara documentos, "
        "pero no certifica pagos ni autenticidad."
    )
