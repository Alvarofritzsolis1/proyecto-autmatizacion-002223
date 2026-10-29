"""GALANT · Control documental de contratistas (Streamlit)."""
from __future__ import annotations

import hashlib
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
from fonasa_nomina_simple import extraer_nomina_fonasa

VERSION = "18.6-Fonasa-simple-preview"
MAX_ARCHIVOS = 20
MAX_BYTES_TOTAL = 60 * 1024 * 1024

st.set_page_config(
    page_title="GALANT | Control Documental",
    page_icon="🛡️",
    layout="wide",
    initial_sidebar_state="collapsed",
)
st.title("GALANT")
st.caption("Control documental de contratistas")
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
                if "fonasa" in str(e.get("institucion", "")).lower()
            ]
            if not paginas:
                # Anexos suelen seguir a la carátula; búsqueda acotada.
                paginas = list(range(2, min(resultado["paginas"], 12) + 1, 2))
            try:
                nomina = extraer_nomina_fonasa(
                    data, paginas_candidatas=paginas,
                )
            except (RuntimeError, ValueError, OSError, ImportError):
                nomina = []
            return resultado, time.perf_counter() - t, nomina

        recibos_ordenados = {}
        pdfs_pago = [
            (i, data, nombre) for i, (data, nombre) in enumerate(previred)
            if nombre.lower().endswith(".pdf")
        ]
        with ThreadPoolExecutor(max_workers=min(3, max(1, len(pdfs_pago)))) as grupo:
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
            pagos_documentales.append(evidencia)
            for anexo in evidencia.get("nomina_fonasa", []):
                for fila in anexo.get("trabajadores", []):
                    nominas_fonasa.append({
                        **fila,
                        "archivo": nombre,
                        "pagina_fonasa": anexo["pagina"],
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
                "Trabajadores Fonasa": sum(
                    len(x.get("trabajadores", []))
                    for x in evidencia.get("nomina_fonasa", [])
                ),
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
        cruzados, resumen_cruce = conciliar_f301_previred(
            certificados, nomina, matriz
        )
        bandeja = generar_bandeja(
            certificados=certificados, incidencias=incidencias,
            detalle=detalle, log=log, cruce_detalle=cruzados,
            cruce_resumen=resumen_cruce, errores=errores, duplicados=duplicados,
            pagos_documentales=pagos_documentales,
        )
        calidad = resumen_calidad(certificados, matriz, bandeja)
        try:
            reporte_excel = informe_consolidado(
                bandeja=bandeja, certificados=certificados, matriz=matriz,
                detalle_cruce=cruzados, resumen_cruce=resumen_cruce,
                log=log, incidencias=incidencias,
            )
        except Exception:
            reporte_excel = None  # No perder la auditoría si el exportador falla.
    st.session_state["reporte_galant"] = {
        "firma": firma, "certificados": certificados,
        "nomina": nomina, "incidencias": incidencias,
        "matriz": matriz, "excel": excel, "detalle": detalle, "log": log,
        "cruce_detalle": cruzados, "cruce_resumen": resumen_cruce,
        "bandeja": bandeja, "calidad": calidad, "reporte_excel": reporte_excel,
        "duplicados": duplicados, "errores": errores,
        "pagos_documentales": pagos_documentales,
        "nominas_fonasa": nominas_fonasa,
        "tiempos_pagos": tiempos_pagos,
        "duracion": time.perf_counter()-inicio,
    }

reporte = st.session_state.get("reporte_galant")
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
    st.markdown("#### Trabajadores declarados en Fonasa")
    st.caption(
        "Nómina simplificada del anexo Fonasa: trabajador, RUT, días "
        "trabajados y período. No se realizan cuadrados de bases imponibles."
    )
    filas_fonasa = []
    for trabajador in reporte.get("nominas_fonasa", []):
        archivo = trabajador.get("archivo", "")
        periodo = ""
        fecha_pago = ""
        folio = ""
        for recibo in reporte.get("pagos_documentales", []):
            if recibo.get("archivo") != archivo:
                continue
            candidatos = [
                x for x in recibo.get("comprobantes", [])
                if "fonasa" in str(x.get("institucion", "")).lower()
            ]
            if candidatos:
                periodos = {x.get("periodo") for x in candidatos if x.get("periodo")}
                fechas = {x.get("fecha_pago") for x in candidatos if x.get("fecha_pago")}
                folios = {x.get("folio") for x in candidatos if x.get("folio")}
                periodo = next(iter(periodos)) if len(periodos) == 1 else "Revisar"
                fecha_pago = next(iter(fechas)) if len(fechas) == 1 else "Revisar"
                folio = next(iter(folios)) if len(folios) == 1 else "Revisar"
            break
        filas_fonasa.append({
            "Archivo": archivo,
            "Nombre trabajador": trabajador.get("trabajador_nombre", ""),
            "RUT": trabajador.get("trabajador_rut", ""),
            "Días trabajados": trabajador.get("dias_trabajados_fonasa"),
            "Período": periodo or "Por confirmar",
            "Fecha pago Fonasa": fecha_pago or "Por confirmar",
            "Folio Fonasa": folio or "Por confirmar",
            "Página anexo": trabajador.get("pagina_fonasa", ""),
            "Observación": (
                "Revisar días en anexo (OCR ambiguo)"
                if trabajador.get("dias_requieren_revision") else ""
            ),
        })
    if filas_fonasa:
        tabla_fonasa = pd.DataFrame(filas_fonasa)
        st.dataframe(tabla_fonasa, hide_index=True, use_container_width=True)
        st.download_button(
            "Descargar trabajadores Fonasa (Excel/CSV)",
            data=tabla_fonasa.to_csv(index=False).encode("utf-8-sig"),
            file_name="GALANT_Trabajadores_Fonasa.csv", mime="text/csv",
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
            "No se pudo localizar una nómina Fonasa confiable en los documentos. "
            "La lectura de comprobantes de pago se muestra por separado."
        )
    st.markdown("#### Estado documental del pago de cotizaciones")
    total_rescate = sum(
        len(doc.get("rapidocr", {}).get("paginas", []))
        for doc in reporte.get("pagos_documentales", [])
    )
    if total_rescate:
        st.caption(
            f"RapidOCR revisó {total_rescate} página(s) escaneada(s) "
            "de forma complementaria a Tesseract."
        )
    sin_rescate = [
        doc["archivo"] for doc in reporte.get("pagos_documentales", [])
        if doc.get("rapidocr", {}).get("estado") == "no_disponible"
    ]
    if sin_rescate:
        st.warning(
            f"El OCR de rescate no estaba disponible en {len(sin_rescate)} "
            "archivo(s). Se conservó la lectura original de Tesseract. "
            "Revisar la instalación de RapidOCR/ONNX."
        )
    filas_pago = []
    for doc_pago in reporte.get("pagos_documentales", []):
        for ev in doc_pago["comprobantes"]:
            filas_pago.append({
                "Archivo": doc_pago["archivo"],
                "Institución": ev["institucion"],
                "Período remuneración": ev["periodo"] or "No legible",
                "Fecha de pago": ev["fecha_pago"] or "No identificada",
                "Estado documental": ev["estado"].replace("_", " ").capitalize(),
                "Página": ev["pagina"],
                "Folio": ev["folio"],
                "Observación": ev["observacion"],
            })
    if filas_pago:
        alertas_fecha = sum(
            any(
                k.startswith("conflicto_") and bool(v)
                for k, v in e.items()
            )
            for doc in reporte.get("pagos_documentales", [])
            for e in doc.get("comprobantes", [])
        )
        sin_folio = sum(
            not bool(e.get("folio"))
            for doc in reporte.get("pagos_documentales", [])
            for e in doc.get("comprobantes", [])
        )
        sin_institucion = sum(
            "no identificada" in str(e.get("institucion", "")).lower()
            for doc in reporte.get("pagos_documentales", [])
            for e in doc.get("comprobantes", [])
        )
        if alertas_fecha:
            st.error(
                f"{alertas_fecha} comprobante(s) con datos OCR contradictorios "
                "entre dos lecturas (fecha, folio, período o institución). "
                "Revisar la página antes de aprobar el pago."
            )
        if sin_folio or sin_institucion:
            st.warning(
                f"Identificación parcial: {sin_folio} comprobante(s) sin folio "
                f"y {sin_institucion} sin institución identificada. "
                "Aunque exista fecha de pago, confirmar el respaldo antes de aprobar."
            )
        completos = sum(
            bool(e.get("periodo") and e.get("fecha_pago"))
            for doc in reporte.get("pagos_documentales", [])
            for e in doc.get("comprobantes", [])
        )
        st.caption(
            f"Comprobantes con fecha y período: {completos} de {len(filas_pago)}. "
            "Los restantes requieren revisión; no se clasifican como impagos."
        )
        tabla_pago = pd.DataFrame(filas_pago)
        st.dataframe(tabla_pago, hide_index=True, use_container_width=True)
        st.download_button(
            "Descargar respaldo de pagos (CSV compatible con Excel)",
            data=tabla_pago.to_csv(index=False).encode("utf-8-sig"),
            file_name="GALANT_Respaldo_Pagos.csv",
            mime="text/csv",
        )
        incompletos = [
            x for x in reporte["pagos_documentales"] if not x["revision_integral"]
        ]
        if incompletos:
            st.warning(
                "Algunos PDF son escaneados y la lectura rápida revisa páginas "
                "prioritarias. Los pagos mostrados tienen evidencia documental, "
                "pero aún pueden faltar instituciones o períodos por leer."
            )
    else:
        st.info("Sin comprobantes de pago suficientes. Esto no significa que las cotizaciones estén impagas.")
    st.caption(
        "El estado proviene de los documentos: no equivale a confirmación "
        "oficial de Previred ni de la institución recaudadora."
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
                "La lectura prioriza estado de pago, fecha y período. "
                "La revisión de nóminas es opcional."
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
                "Revisa también el estado de los comprobantes en la tabla superior."
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
