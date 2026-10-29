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

VERSION = "19.0-UI-preview"
MAX_ARCHIVOS = 20
MAX_BYTES_TOTAL = 60 * 1024 * 1024

st.set_page_config(
    page_title="GALANT | Control Documental",
    page_icon="🛡️",
    layout="wide",
    initial_sidebar_state="collapsed",
)
# Presentación independiente del motor de auditoría: el OCR y las reglas
# documentales permanecen en sus módulos especializados.
st.markdown(
    """
    <style>
    [data-testid="stAppViewContainer"] {
        background: #F5F7FC;
    }
    .block-container {
        max-width: 1270px;
        padding-top: 2.0rem;
        padding-bottom: 4rem;
    }
    [data-testid="stHeader"] {
        background: rgba(245,247,252,0.94);
    }
    .galant-hero {
        padding: 2.4rem 2.6rem;
        border-radius: 22px;
        background: linear-gradient(120deg, #102641 0%, #184E8B 68%, #2370B7 100%);
        color: #FFFFFF;
        box-shadow: 0 16px 32px rgba(16,38,65,.13);
        margin: 0 0 1.9rem 0;
    }
    .galant-hero .eyebrow {
        text-transform: uppercase;
        font-size: .82rem;
        letter-spacing: .12em;
        font-weight: 700;
        color: #BBD9FE;
        margin: 0 0 .7rem 0;
    }
    .galant-hero h1 {
        font-size: clamp(1.8rem,3.3vw,2.8rem);
        font-weight: 760;
        letter-spacing: -.035em;
        color: #FFFFFF !important;
        margin: 0 0 .7rem 0;
        line-height: 1.15;
    }
    .galant-hero p {
        color: #DBEAFE;
        font-size: 1.04rem;
        max-width: 780px;
        margin: 0;
    }
    div[data-testid="stVerticalBlockBorderWrapper"] > div {
        border-radius: 16px;
    }
    div[data-testid="stFileUploader"] {
        padding: .45rem .8rem;
        background: #F8FAFF;
        border: 1px solid #DFE8F5;
        border-radius: 12px;
    }
    div[data-testid="stMetric"] {
        background: #FFFFFF;
        border: 1px solid #E3EAF4;
        border-radius: 16px;
        padding: 1.25rem 1.4rem;
        box-shadow: 0 3px 15px rgba(16,38,65,.04);
    }
    button[kind="primary"] {
        border-radius: 10px;
        background: #2463D4;
        border-color: #2463D4;
        font-weight: 650;
        padding: .7rem 1.2rem;
        min-height: 2.8rem;
    }
    button[kind="primary"]:hover {
        background: #174FAF;
        border-color: #174FAF;
    }
    div[data-testid="stDataFrame"], div[data-testid="stExpander"] {
        border-radius: 14px;
        overflow: hidden;
    }
    @media (max-width: 700px) {
        .block-container { padding: 1.2rem 1rem 3rem; }
        .galant-hero { padding: 1.5rem; border-radius: 16px; }
        .galant-hero p { font-size: .95rem; }
    }
    </style>
    """,
    unsafe_allow_html=True,
)
st.markdown(
    """
    <section class="galant-hero">
      <p class="eyebrow">GALANT · Control documental de contratistas</p>
      <h1>Tu documentación, bajo control.</h1>
      <p>Analiza certificados F30-1 y documentos previsionales con una
      revisión ordenada, trazable y fácil de consultar.</p>
    </section>
    """,
    unsafe_allow_html=True,
)
st.markdown("### 1. Cargar documentos")
st.caption(
    "Puedes subir solo cotizaciones, solo certificados F30-1 o ambos. "
    "GALANT identifica el tipo por el contenido para evitar errores de clasificación."
)
col_cotizaciones, col_certificados = st.columns(2, gap="large")
with col_cotizaciones:
    with st.container(border=True):
        st.markdown("#### 🧾 Cotizaciones previsionales")
        st.caption("Comprobantes de pago, Previred y planillas de cotizaciones.")
        cotizaciones_subidas = st.file_uploader(
            "Subir cotizaciones (PDF, Excel o CSV)",
            type=["pdf", "xlsx", "xls", "csv"],
            accept_multiple_files=True,
            max_upload_size=25,
            key="galant_upload_cotizaciones",
        )

with col_certificados:
    with st.container(border=True):
        st.markdown("#### 📄 Certificados F30-1")
        st.caption("Certificados de cumplimiento de obligaciones laborales y previsionales.")
        certificados_subidos = st.file_uploader(
            "Subir F30-1 (PDF)",
            type=["pdf"],
            accept_multiple_files=True,
            max_upload_size=25,
            key="galant_upload_f301",
        )

archivos = list(cotizaciones_subidas or []) + list(certificados_subidos or [])
st.caption(f"{len(archivos)} archivo(s) seleccionado(s) · Límite: {MAX_ARCHIVOS} archivos / 60 MB.")
limite_excedido = len(archivos) > MAX_ARCHIVOS or sum(a.size for a in archivos) > MAX_BYTES_TOTAL
if limite_excedido:
    st.error("Se excedió el máximo de 20 archivos o 60 MB. Divide la carga.")

with st.expander("⚙️ Configuración avanzada · opcional", expanded=False):
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
    st.markdown("### 2. Resultados del análisis")
    st.caption("Resultados basados en los documentos cargados: no equivalen a verificación oficial de pago.")
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

    st.markdown("#### Observaciones y acciones recomendadas")
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

    with st.expander("📁 Explorar documentos y trabajadores", expanded=True):
        if not matriz.empty:
            st.markdown("#### 🧾 Cotizaciones previsionales")
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
            st.markdown("#### 📄 Certificados F30-1")
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
            st.markdown("#### 🔎 Comparación documental")
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
