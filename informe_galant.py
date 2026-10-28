"""Informe consolidado GALANT para revisión y respaldo interno.

Se genera en memoria. Las celdas no se interpretan como fórmulas ni hipervínculos.
El informe no certifica pago efectivo ni autenticidad ante la DT.
"""
from __future__ import annotations
import io
from datetime import datetime, timezone
import pandas as pd

ENCABEZADO = "GALANT | CONTROL DOCUMENTAL"

def informe_consolidado(
    bandeja: pd.DataFrame,
    certificados: list[dict],
    matriz: pd.DataFrame,
    detalle_cruce: pd.DataFrame,
    resumen_cruce: pd.DataFrame,
    log: pd.DataFrame,
    incidencias: list[dict] | None = None,
) -> bytes:
    """Exportar hallazgos y evidencia, sin adjuntar los PDF originales."""
    salida = io.BytesIO()
    certs = pd.DataFrame(certificados or [])
    items = bandeja if bandeja is not None else pd.DataFrame()
    resumen = pd.DataFrame([
        {"indicador": "Certificados F30-1 leídos", "valor": len(certs)},
        {"indicador": "Registros de cotizaciones", "valor": 0 if matriz is None else len(matriz)},
        {"indicador": "Casos para revisar", "valor": len(items)},
        {"indicador": "Casos prioridad alta", "valor": 0 if items.empty else int(items["prioridad"].eq("ALTA").sum())},
        {"indicador": "Verificación oficial DT", "valor": "PENDIENTE; consultar en DT"},
        {"indicador": "Alcance del informe",
         "valor": "Cruce documental: no acredita pago ni obligaciones legales"}
    ])
    hojas = [
        ("Resumen", resumen),
        ("Bandeja_Revision", items),
        ("Certificados_F301", certs),
        ("Cruce_Resumen", resumen_cruce),
        ("Cruce_Trabajadores", detalle_cruce),
        ("Cotizaciones", matriz),
        ("Procesamiento", log),
        ("OCR_F301", pd.DataFrame(incidencias or [])),
    ]
    with pd.ExcelWriter(
        salida, engine="xlsxwriter",
        engine_kwargs={
            "options": {"strings_to_formulas": False, "strings_to_urls": False}
        }
    ) as writer:
        libro = writer.book
        cabecera = libro.add_format({
            "bold": True, "font_color": "#FFFFFF", "bg_color": "#1D3557",
            "border": 0, "text_wrap": True, "valign": "vcenter"
        })
        alto = libro.add_format({"bg_color": "#FBE1DE", "font_color": "#8C2020"})
        medio = libro.add_format({"bg_color": "#FFF0CC", "font_color": "#725600"})
        bajo = libro.add_format({"bg_color": "#E6F2E6", "font_color": "#245B24"})
        for nombre, dataframe in hojas:
            df = dataframe if dataframe is not None else pd.DataFrame()
            if df.empty and not len(df.columns):
                df = pd.DataFrame(columns=["Sin datos en esta carga"])
            df.to_excel(writer, sheet_name=nombre, index=False)
            ws = writer.sheets[nombre]
            ws.freeze_panes(1, 0)
            ws.hide_gridlines(2)
            ws.set_row(0, 34)
            for columna, nombre_col in enumerate(df.columns):
                ws.write(0, columna, str(nombre_col), cabecera)
                muestras = df.iloc[:250, columna].astype(str).tolist()
                ancho = max([len(str(nombre_col))]+[min(len(x), 65) for x in muestras])
                ws.set_column(columna, columna, min(57, max(15, ancho+3)))
            if len(df):
                ws.autofilter(0, 0, len(df), len(df.columns)-1)
            if nombre == "Bandeja_Revision" and len(df):
                ws.conditional_format(
                    1, 0, len(df), 0,
                    {"type": "text", "criteria": "containing",
                     "value": "ALTA", "format": alto}
                )
                ws.conditional_format(
                    1, 0, len(df), 0,
                    {"type": "text", "criteria": "containing",
                     "value": "MEDIA", "format": medio}
                )
                ws.conditional_format(
                    1, 0, len(df), 0,
                    {"type": "text", "criteria": "containing",
                     "value": "BAJA", "format": bajo}
                )
        libro.set_properties({
            "title": ENCABEZADO,
            "subject": "Informe documental de contratistas",
            "comments": "No acredita pago ni verificación oficial DT."
        })
    return salida.getvalue()
