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

VERSION = "17.0"
MAX_ARCHIVOS = 20
MAX_BYTES_TOTAL = 60 * 1024 * 1024

st.set_page_config(
    page_title="GALANT | Control Documental",
    page_icon="🛡️",
    layout="wide",
    initial_sidebar_state="collapsed",
)
st.title("GALANT")
st.caption("Control documental de contratistas · F30-1, Previred y cotizaciones previsionales")
st.write("Sube los documentos, presiona **Analizar** y revisa únicamente las diferencias detectadas.")

with st.expander("Alcance y privacidad del análisis", expanded=False):
    st.write(
        "GALANT compara información extraída de F30-1, AFP, Salud, Mutual/ISL "
        "y Seguro Social. Un RUT coincidente no acredita que las cotizaciones estén pagadas. "
        "Los certificados F30-1 no se autentican automáticamente ante la DT. "
        "Los documentos se procesan en memoria sin subirlos al repositorio de GitHub."
    )
    st.warning(
        "Los documentos pueden contener datos personales y remuneraciones. "
        "Restringe el acceso a Streamlit antes de analizar información laboral real. "
        "No subas certificados ni nóminas al GitHub público."
    )

st.subheader("1. Subir documentación")
archivos_subidos = st.file_uploader(
    "F30-1, comprobantes de cotizaciones o Excel/CSV",
    type=["pdf", "xlsx", "xls", "csv"],
    accept_multiple_files=True,
    max_upload_size=25,
    help=f"Hasta {MAX_ARCHIVOS} archivos y 60 MB en total. Los PDF escaneados usan OCR.",
)
archivos = list(archivos_subidos or [])
limite_excedido = len(archivos) > MAX_ARCHIVOS or sum(a.size for a in archivos) > MAX_BYTES_TOTAL
if limite_excedido:
    st.error("Se excedió el máximo de 20 archivos o 60 MB. Divide la carga.")

with st.expander("Opciones avanzadas (normalmente no es necesario cambiarlas)", expanded=False):
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
    st.info("Cambiaste los documentos o las opciones. Presiona «Analizar documentos» para actualizar.")
elif reporte:
    st.subheader("2. Resultado de la revisión")
    matriz = reporte["matriz"]
    certificados = reporte["certificados"]
    resumen_cruce = reporte["cruce_resumen"]
    estados = matriz["estado_auditoria"].value_counts() if "estado_auditoria" in matriz else {}
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("F30-1 leídos", len(certificados))
    m2.metric("Nóminas F30-1 completas", reporte["calidad"]["nominas_completas"])
    m3.metric("Bases sin observaciones", int(estados.get("CONFORME", 0)))
    m4.metric("Casos prioridad alta", reporte["calidad"]["pendientes_prioridad_alta"])
    st.caption(
        f"Tiempo: {reporte['duracion']:.1f} segundos. "
        "«Sin observaciones» significa solo cuadratura según reglas configuradas, no cumplimiento legal."
    )

    if reporte["duplicados"]:
        st.info(
            f"Se omitieron {len(reporte['duplicados'])} archivos idénticos "
            "para evitar procesarlos dos veces."
        )
    for error in reporte["errores"]:
        st.error("Un grupo de archivos no se pudo procesar: " + error)

    if not reporte["errores"] and not certificados and matriz.empty:
        st.warning("No se recuperaron registros. Revisa si los archivos contienen páginas legibles.")

    tab_revision, tab_resumen, tab_f301, tab_previred = st.tabs(
        ["Qué revisar", "Cruce F30-1 / Previred", "Certificados F30-1", "Cotizaciones"]
    )
    with tab_revision:
        st.markdown("**Bandeja de excepciones por prioridad**")
        st.caption(
            "GALANT muestra solo información que necesita revisión. "
            "ALTA, MEDIA y BAJA son prioridades de trabajo, no calificaciones legales."
        )
        pendientes = reporte["bandeja"]
        if pendientes.empty:
            st.success(
                "No se identificaron excepciones en los documentos disponibles. "
                "Esto no certifica el pago ni la autenticidad de los certificados."
            )
        else:
            prioridades = st.multiselect(
                "Prioridad", ["ALTA", "MEDIA", "BAJA"],
                default=["ALTA", "MEDIA"],
                help="Selecciona también BAJA para ver archivos duplicados.",
                key="prioridades_galant",
            )
            visible = pendientes.loc[pendientes["prioridad"].isin(prioridades)]
            st.dataframe(
                visible, hide_index=True, use_container_width=True,
                column_config={
                    "hallazgo": st.column_config.TextColumn("Qué se detectó", width="large"),
                    "accion_recomendada": st.column_config.TextColumn("Qué hacer", width="large"),
                },
            )
            st.caption(
                f"{len(pendientes)} casos identificados. "
                "El archivo y la página se muestran cuando el extractor pudo reconocerlos."
            )
        if reporte.get("reporte_excel"):
            st.download_button(
                "Descargar informe completo GALANT (.xlsx)",
                data=reporte["reporte_excel"],
                file_name="GALANT_Informe_Documental.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                type="primary",
            )
        else:
            st.warning("No se pudo generar el informe consolidado en esta ejecución.")
    with tab_resumen:
        if not resumen_cruce.empty:
            st.markdown("**Cruce F30-1 ↔ Previred por empresa, período y RUT**")
            st.dataframe(
                resumen_cruce[[
                    "contratista", "periodo", "trabajadores_declarados",
                    "trabajadores_reconocidos", "rut_coincidentes",
                    "rut_pendientes", "resultado", "accion"
                ]],
                hide_index=True, use_container_width=True,
            )
            st.caption(
                "Previred puede incluir otras obras de la misma empresa: "
                "no se marca como incumplimiento tener trabajadores adicionales allí. "
                "El pago y la autenticidad de la DT se validan por separado."
            )
            st.download_button(
                "Descargar detalle del cruce (CSV)",
                data=reporte["cruce_detalle"].to_csv(index=False).encode("utf-8-sig"),
                file_name="GALANT_Cruce_F301_Previred.csv",
                mime="text/csv"
            )
        elif certificados:
            st.info("Los F30-1 se identificaron, pero falta un comprobante comparable o una nómina recuperable.")
        else:
            st.info("Carga al menos un F30-1 para cotejar su nómina con Previred.")
        pendientes_f301 = [
            c for c in certificados
            if c.get("observaciones")
            or c.get("cotizaciones") != "SI_DECLARADO_EN_PDF"
        ]
        if pendientes_f301:
            st.warning(
                f"{len(pendientes_f301)} certificado(s) requieren revisión "
                "de integridad, resumen o extracción."
            )
        if not reporte["cruce_detalle"].empty:
            with st.expander("Trabajadores cotejados y acción sugerida"):
                filtro = st.checkbox(
                    "Mostrar solo RUT con diferencias o pendientes",
                    value=True, key="filtrar_cruce_galant"
                )
                tabla = reporte["cruce_detalle"]
                if filtro:
                    tabla = tabla.loc[tabla["resultado"].ne("RUT_COINCIDE")]
                st.dataframe(tabla, use_container_width=True, hide_index=True)

    with tab_f301:
        if not certificados:
            st.info("No se cargaron certificados F30-1.")
        for cert in certificados:
            with st.container(border=True):
                st.markdown(
                    f"**{cert.get('contratista') or 'Empleador no identificado'}** "
                    f"· período **{cert.get('periodo') or 'no identificado'}**"
                )
                c1, c2, c3 = st.columns(3)
                c1.metric("Declarados", cert.get("trabajadores_declarados")
                          if cert.get("trabajadores_declarados") is not None else "?")
                c2.metric("RUT recuperados", cert.get("trabajadores_identificados", 0))
                c3.metric("Páginas", cert.get("paginas", ""))
                if cert.get("cotizaciones") == "SI_DECLARADO_EN_PDF":
                    st.info("El PDF declara cotizaciones pagadas; la DT aún no se ha verificado.")
                elif cert.get("cotizaciones") == "SIN_RESUMEN_NO_SE_PUEDE_CONFIRMAR":
                    st.warning(
                        "Falta página de resumen. El estado de pago no es verificable "
                        "con este archivo (no significa impago)."
                    )
                else:
                    st.warning("Estado de pago no confirmado con este certificado.")
                if cert.get("observaciones"):
                    st.caption("Revisión necesaria: " + cert["observaciones"])
                st.caption(
                    f"Folio: {cert.get('folio', '')} · "
                    "Autenticidad pendiente de verificación en DT."
                )
        if reporte["nomina"]:
            with st.expander("Nómina detallada extraída del F30-1"):
                st.dataframe(pd.DataFrame(reporte["nomina"]),
                             use_container_width=True, hide_index=True)
        st.link_button("Abrir verificador oficial DT", "https://verificador.dirtrab.cl/")

    with tab_previred:
        if matriz.empty:
            st.info("No hay cotizaciones Previred procesadas en esta carga.")
        else:
            revisar = matriz.loc[matriz["estado_auditoria"].ne("CONFORME")]
            solo = st.checkbox("Ver primero los registros que necesitan revisión", value=True)
            st.dataframe(
                (revisar if solo else matriz).reindex(columns=COLUMNAS_SALIDA),
                use_container_width=True, hide_index=True
            )
            if revisar.empty:
                st.success(
                    "Las bases documentales comparadas no muestran diferencias "
                    "según los controles configurados. No equivale a pago acreditado."
                )
            if reporte.get("excel") is not None:
                st.download_button(
                    "Descargar auditoría Excel",
                    data=reporte["excel"],
                    file_name="GALANT_Auditoria_Documental.xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    type="primary",
                )
        if reporte["detalle"] is not None and not reporte["detalle"].empty:
            with st.expander("Causas y páginas de revisión de cotizaciones"):
                st.dataframe(reporte["detalle"], hide_index=True, use_container_width=True)
        if reporte["log"] is not None and not reporte["log"].empty:
            with st.expander("Procesamiento y errores por archivo"):
                st.dataframe(reporte["log"], hide_index=True, use_container_width=True)
        if reporte["incidencias"]:
            with st.expander("Lecturas F30-1 que necesitan revisión"):
                st.dataframe(pd.DataFrame(reporte["incidencias"]),
                             hide_index=True, use_container_width=True)
