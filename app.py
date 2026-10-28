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

VERSION = "18.3"
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
    with st.spinner("Leyendo documentos y conciliando sus respaldos..."):
        f301, previred = [], []
        for data, nombre in entradas:
            if nombre.lower().endswith(".pdf") and es_f301(data, nombre):
                f301.append((data, nombre))
            else:
                previred.append((data, nombre))
        if f301:
            certificados, nomina, incidencias = analizar_f301(f301)
        if previred:
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

    st.markdown("**Qué revisar**")
    if pendientes.empty:
        if reporte["errores"] or archivos_leidos == 0:
            st.warning("No hay resultados suficientes. Revisa los archivos que no se pudieron leer.")
        else:
            st.success("No se detectaron diferencias en los documentos leídos.")
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
