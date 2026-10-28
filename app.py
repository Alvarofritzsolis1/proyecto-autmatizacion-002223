from __future__ import annotations

import hashlib
import time
import streamlit as st

from auditoria_laboral import (
    COLUMNAS_SALIDA,
    ejecutar_pipeline,
    plantilla_topes_csv,
)

st.set_page_config(
    page_title="Auditoría Laboral de Contratistas",
    page_icon="📊",
    layout="wide",
)

st.title("📊 Auditoría laboral de contratistas")
st.caption("Carga planillas, revisa alertas y descarga una matriz Excel estandarizada.")

# Chat visible desde que se abre la aplicación, incluso sin archivos cargados.
from chat_asesor import mostrar_chat
with st.container(border=True):
    mostrar_chat(st.session_state.get("reporte_auditoria"))


with st.expander("Antes de comenzar: qué hace y qué no hace", expanded=True):
    st.write(
        "El sistema lee Excel/CSV y comprobantes PDF, y reconoce los anexos de Previred "
        "(Seguro Social, AFP, Salud y Mutual/ISL). Cruza las bases imponibles por RUT, "
        "suma solamente movimientos de la MISMA fuente y obtiene los días efectivos "
        "de Salud o Seguro Social. Verifica los totales contra los resúmenes disponibles. "
        "En escaneos Previred compatibles identifica páginas y celdas relevantes antes de "
        "usar OCR (sin leer todas las portadas). No inventa importes: "
        "cuando falta respaldo o hay discrepancias OCR, marca REVISAR_DATOS."
    )
    st.warning(
        "Los archivos pueden contener datos personales y laborales. No subas documentos "
        "a una app pública sin autorización. El código procesa los archivos en memoria y "
        "no los guarda como archivos permanentes, pero el servicio se ejecuta en la nube."
    )

st.subheader("1. Cargar documentos")
MAX_ARCHIVOS = 20
MAX_BYTES_TOTAL = 60 * 1024 * 1024  # Protección frente a límites de memoria del hosting gratuito.
archivos_subidos = st.file_uploader(
    "Selecciona una o varias planillas de remuneraciones",
    type=["xlsx", "xls", "csv", "pdf"],
    accept_multiple_files=True,
    max_upload_size=25,
    help=(
        "Límite de esta app: 20 archivos y 60 MB en total. Los PDF escaneados se procesan con OCR "
        "automático (lector especializado hasta 120 páginas; genérico hasta 60). El OCR puede requerir revisión si está "
        "borroso o la tabla no tiene columnas claras."
    ),
)

bytes_documentos = sum(f.size for f in (archivos_subidos or []))
limite_excedido = bool(archivos_subidos) and (
    len(archivos_subidos) > MAX_ARCHIVOS or bytes_documentos > MAX_BYTES_TOTAL
)
if archivos_subidos and len(archivos_subidos) > MAX_ARCHIVOS:
    st.error(f"Has seleccionado {len(archivos_subidos)} archivos. El máximo permitido es {MAX_ARCHIVOS}.")
if archivos_subidos and bytes_documentos > MAX_BYTES_TOTAL:
    st.error(f"El total seleccionado es {bytes_documentos / (1024 * 1024):.1f} MB. El máximo es 60 MB.")

col1, col2 = st.columns(2)
with col1:
    tolerancia = st.number_input(
        "Tolerancia para diferencias entre bases imponibles (CLP)",
        min_value=0,
        max_value=100000,
        value=15,
        step=5,
        help="No es una tasa de cotización. Es la diferencia máxima permitida al comparar bases declaradas.",
    )
with col2:
    incluir_mutual = st.checkbox(
        "Incluir renta imponible Mutual en el cuadre de bases",
        value=True,
        help=(
            "Desmárcalo solo si tu procedimiento compara Salud y AFP y revisa la base Mutual por separado. "
            "La mutual adherida sigue siendo un dato requerido para emitir CONFORME."
        ),
    )

with st.expander("2. Opcional: topes imponibles por período (solo para rentas altas)", expanded=False):
    st.caption(
        "No necesitas subir un CSV de topes para analizar los importes del PDF de ejemplo. "
        "Los topes solo se aplican si subes una tabla oficial para el período."
    )
    st.download_button(
        "Descargar plantilla CSV de topes",
        data=plantilla_topes_csv(),
        file_name="topes_imponibles_plantilla.csv",
        mime="text/csv",
    )
    topes_subido = st.file_uploader(
        "Tabla de topes en CLP por período (CSV; opcional)",
        type=["csv"],
        accept_multiple_files=False,
        max_upload_size=2,
        key="topes_csv",
        help="Usar únicamente topes verificados por período; no subas nóminas aquí.",
    )
if topes_subido and topes_subido.size > 2 * 1024 * 1024:
    st.error("La tabla de topes supera 2 MB. Revisa que sea solo el CSV de referencia.")
    limite_excedido = True

if st.button(
    "Ejecutar auditoría",
    type="primary",
    disabled=(not archivos_subidos or limite_excedido),
):
    # Elimina el reporte anterior para que nunca se muestre como vigente si falla una nueva ejecución.
    st.session_state.pop("reporte_auditoria", None)
    entradas = [(f.getvalue(), f.name) for f in archivos_subidos]
    topes_bytes = topes_subido.getvalue() if topes_subido else None
    # Se firma el input para no mostrar por error un reporte de una carga previa.
    firma = hashlib.sha256()
    for contenido, nombre in entradas:
        firma.update(nombre.encode("utf-8", errors="ignore"))
        firma.update(contenido)
    if topes_bytes:
        firma.update(topes_bytes)
    firma.update(str(int(tolerancia)).encode())
    firma.update(str(bool(incluir_mutual)).encode())

    try:
        comienzo = time.perf_counter()
        with st.spinner("Leyendo anexos relevantes y ejecutando auditoría (OCR selectivo para escaneos)..."):
            matriz, excel_bytes, detalle, log = ejecutar_pipeline(
                entradas,
                topes_csv=topes_bytes,
                nombre_topes=topes_subido.name if topes_subido else "topes.csv",
                tolerancia_clp=int(tolerancia),
                incluir_mutual=incluir_mutual,
            )
        st.session_state["reporte_auditoria"] = {
            "firma": firma.hexdigest(),
            "matriz": matriz,
            "excel": excel_bytes,
            "detalle": detalle,
            "log": log,
            "duracion_s": round(time.perf_counter() - comienzo, 2),
        }
    except Exception as exc:
        st.error(f"No se pudo completar la auditoría: {exc}")

# Solo mostrar los resultados si corresponden a los archivos y opciones actuales.
reporte = st.session_state.get("reporte_auditoria")
if reporte:
    firma_actual = hashlib.sha256()
    if archivos_subidos:
        for f in archivos_subidos:
            firma_actual.update(f.name.encode("utf-8", errors="ignore"))
            firma_actual.update(f.getvalue())
    if topes_subido:
        firma_actual.update(topes_subido.getvalue())
    firma_actual.update(str(int(tolerancia)).encode())
    firma_actual.update(str(bool(incluir_mutual)).encode())
    if firma_actual.hexdigest() == reporte["firma"]:
        matriz = reporte["matriz"]
        st.caption(f"Tiempo de procesamiento: {reporte.get('duracion_s', 0):.1f} segundos. "
                   "Varía según calidad del escaneo, cantidad de páginas y capacidad del servidor.")
        resumen = matriz["estado_auditoria"].value_counts()
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Registros", len(matriz))
        c2.metric("🟢 Conformes", int(resumen.get("CONFORME", 0)))
        c3.metric("🔴 Alertas", int(matriz["estado_auditoria"].str.startswith("ALERTA").sum()))
        c4.metric("🟡 Revisar datos", int(resumen.get("REVISAR_DATOS", 0)))

        st.subheader("Matriz de auditoría")
        st.dataframe(matriz.reindex(columns=COLUMNAS_SALIDA), use_container_width=True, hide_index=True)

        if not reporte["detalle"].empty:
            st.subheader("Registros con alerta o revisión")
            st.dataframe(reporte["detalle"], use_container_width=True, hide_index=True)
        else:
            st.success("No se encontraron registros que requieran revisión según las reglas configuradas.")

        st.subheader("Resultado por archivo")
        st.dataframe(reporte["log"], use_container_width=True, hide_index=True)

        st.download_button(
            "📥 Descargar matriz Excel de auditoría",
            data=reporte["excel"],
            file_name="Matriz_Auditoria_Subcontratistas.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            type="primary",
        )
    else:
        st.info("Cambiaste los archivos o las opciones después del último análisis. Ejecuta nuevamente la auditoría para actualizar el informe.")

