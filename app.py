"""GALANT · Control documental de contratistas (Streamlit)."""
from __future__ import annotations

import hashlib
import time
import pandas as pd
import streamlit as st

from auditoria_laboral import COLUMNAS_SALIDA, ejecutar_pipeline, plantilla_topes_csv
from cruce_documental_galant import conciliar_f301_previred
from f301_lector import analizar_f301, es_f301
from bandeja_revision import generar_bandeja, resumen_calidad
from informe_galant import informe_consolidado
from pago_documental import analizar_pago_pdf

VERSION = "18.4"
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
        "Ejecutar además la auditoría avanzada de nóminas y bases imponibles",
        value=False,
        help="La revisión rápida de respaldo de pago, fecha y período funciona sin extraer toda la nómina.",
    )
    lectura_ampliada = st.checkbox(
        "Ampliar la búsqueda en escaneos con muchas instituciones",
        value=False,
        help="Lee hasta 20 páginas candidatas por PDF. Aumenta la cobertura, pero tarda más.",
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
    tiempos_pagos = []
    cache_sesion = st.session_state.setdefault("galant_cache_pago", {})
    with st.spinner("Leyendo documentos y conciliando sus respaldos..."):
        f301, previred = [], []
        for data, nombre in entradas:
            if nombre.lower().endswith(".pdf") and es_f301(data, nombre):
                f301.append((data, nombre))
            else:
                previred.append((data, nombre))
        # La evidencia de pago se procesa ANTES y de manera independiente
        # de la nómina. Un OCR de tablas fallido no descarta un recibo pagado.
        for data, nombre in previred:
            if not nombre.lower().endswith(".pdf"):
                continue
            try:
                inicio_pdf = time.perf_counter()
                clave_cache = VERSION + ":" + hashlib.sha256(data).hexdigest() + ":" + str(lectura_ampliada)
                reutilizado = clave_cache in cache_sesion
                if reutilizado:
                    evidencia = dict(cache_sesion[clave_cache])
                else:
                    evidencia = analizar_pago_pdf(
                        data, nombre, max_paginas_ocr=20 if lectura_ampliada else 6
                    )
                    cache_sesion[clave_cache] = dict(evidencia)
                    # Caché privada de esta sesión; nunca guardar PDFs ni datos
                    # personales en un caché global compartido entre usuarios.
                    if len(cache_sesion) > 50:
                        cache_sesion.pop(next(iter(cache_sesion)))
                evidencia["archivo"] = nombre
                pagos_documentales.append(evidencia)
                tiempos_pagos.append({
                    "Archivo": nombre,
                    "Segundos": round(time.perf_counter() - inicio_pdf, 2),
                    "Páginas": evidencia["paginas"],
                    "Páginas con OCR": evidencia["paginas_ocr"],
                    "Comprobantes detectados": len(evidencia["comprobantes"]),
                    "Comprobantes completos": sum(
                        bool(x.get("periodo") and x.get("fecha_pago"))
                        for x in evidencia["comprobantes"]
                    ),
                    "Caché": "Reutilizado" if reutilizado else "Analizado",
                })
            except Exception as exc:
                errores.append("Lectura de pago: " + nombre + ": " + str(exc)[:250])
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
    st.markdown("#### Estado documental del pago de cotizaciones")
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
    st.markdown("**Qué revisar**")
    if pendientes.empty:
        if reporte["errores"] or archivos_leidos == 0:
            st.warning("No hay resultados suficientes. Revisa los archivos que no se pudieron leer.")
        elif modo_avanzado:
            st.success("No se detectaron diferencias en la revisión avanzada.")
        else:
            st.info("La revisión rápida identifica pagos; la cuadratura detallada es opcional.")
    else:
        columnas = {
            "archivo": "Archivo",
            "rut_trabajador": "RUT trabajador",
            "hallazgo": "Qué revisar",
            "accion_recomendada": "Qué hacer",
        }
        tabla = pendientes.reindex(columns=list(columnas)).rename(columns=columnas)
        st.dataframe(
            tabla, hide_index=True, use_container_width=True,
            column_config={
                "Qué revisar": st.column_config.TextColumn("Qué revisar", width="large"),
                "Qué hacer": st.column_config.TextColumn("Qué hacer", width="large"),
            },
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
