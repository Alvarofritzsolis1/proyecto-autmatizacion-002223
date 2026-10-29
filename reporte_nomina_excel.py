"""Excel de trabajadores y días declarados: generado localmente en Streamlit.

No se exportan datos de montos de AFP/Mutual; se deja evidencia documental
de la institución de salud y página. Nunca inventar días ni pagos.
"""
from __future__ import annotations
from io import BytesIO
import xlsxwriter

COLUMNAS_EXCEL = [
    ("archivo", "Archivo"),
    ("nombre", "Trabajador"),
    ("rut", "RUT"),
    ("sistema", "Sistema de salud"),
    ("institucion_salud", "Institución"),
    ("periodo", "Período remuneración"),
    ("dias", "Días informados"),
    ("situacion", "Estado del respaldo"),
    ("fecha_pago", "Fecha pago documento"),
    ("folio", "Folio"),
    ("pagina_planilla", "Página planilla"),
    ("pagina_comprobante", "Página comprobante"),
    ("observacion", "Observaciones"),
]


def generar_excel_nomina(filas, alertas=None) -> bytes:
    """XLSX auténtico en memoria. Una fila = trabajador / período / institución."""
    alertas = list(alertas or [])
    memoria = BytesIO()
    workbook = xlsxwriter.Workbook(memoria, {
        "in_memory": True, "strings_to_urls": False,
        "strings_to_formulas": False,
    })
    try:
        workbook.set_properties({
            "title": "GALANT - Nómina de días cotizados",
            "subject": "Trabajadores de Fonasa e Isapres",
            "comments": "Evidencia de planillas PDF; no certificación oficial",
        })
        encabezado = workbook.add_format({
            "bold": True, "font_color": "#FFFFFF",
            "bg_color": "#152D44", "text_wrap": True,
            "valign": "vcenter", "border": 0,
        })
        normal = workbook.add_format({"valign": "top"})
        entero = workbook.add_format({"num_format": "0", "valign": "top"})
        pendiente = workbook.add_format({
            "font_color": "#9A5B10", "bg_color": "#FFF2D5",
        })
        titulo = workbook.add_format({
            "bold": True, "font_size": 15,
            "font_color": "#152D44",
        })

        sheet = workbook.add_worksheet("Trabajadores")
        sheet.hide_gridlines(2)
        sheet.set_row(0, 31)
        sheet.freeze_panes(1, 0)
        for j, (_, nombre) in enumerate(COLUMNAS_EXCEL):
            sheet.write_string(0, j, nombre, encabezado)
        ancho = [37, 32, 18, 18, 22, 21, 15, 25, 20, 24, 17, 20, 46]
        for j, ancho_col in enumerate(ancho):
            sheet.set_column(j, j, ancho_col)

        for i, fila in enumerate(filas, start=1):
            sheet.set_row(i, 21)
            for j, (clave, _) in enumerate(COLUMNAS_EXCEL):
                valor = fila.get(clave)
                if clave == "dias":
                    if isinstance(valor, int) and 0 <= valor <= 31:
                        sheet.write_number(i, j, valor, entero)
                    else:
                        sheet.write_blank(i, j, None, pendiente)
                elif valor is None or valor == "":
                    sheet.write_blank(i, j, None, normal)
                elif isinstance(valor, int):
                    sheet.write_number(i, j, valor, entero)
                else:
                    sheet.write_string(i, j, str(valor), normal)
            if fila.get("dias") is None or "revisar" in str(
                fila.get("situacion", "")
            ).lower():
                sheet.write_string(
                    i, 7, str(fila.get("situacion") or "Revisar"), pendiente
                )
        sheet.autofilter(0, 0, max(len(filas), 1), len(COLUMNAS_EXCEL) - 1)

        resumen = workbook.add_worksheet("Resumen")
        resumen.hide_gridlines(2)
        resumen.set_column(0, 0, 37)
        resumen.set_column(1, 1, 24)
        resumen.merge_range("A1:B1", "GALANT · Resumen de cotizaciones", titulo)
        confirmados = sum(
            r.get("situacion") == "Pago respaldado en PDF" for r in filas
        )
        fona = sum(r.get("sistema") == "Fonasa" for r in filas)
        isa = sum(r.get("sistema") == "Isapre" for r in filas)
        datos = [
            ("Trabajadores / períodos en nómina", len(filas)),
            ("Con respaldo documental de pago", confirmados),
            ("Pendientes de revisar", len(filas) - confirmados),
            ("Registros Fonasa", fona),
            ("Registros Isapre", isa),
            ("Archivos con Isapre sin nómina", len(alertas)),
        ]
        for idx, (nombre, cantidad) in enumerate(datos, start=2):
            resumen.write_string(idx, 0, nombre)
            resumen.write_number(idx, 1, cantidad, entero)
        resumen.write_string(10, 0, "Alcance", encabezado)
        resumen.merge_range(
            "A12:B13",
            "Los días proceden de planillas de salud y los pagos "
            "de comprobantes documentales del PDF. "
            "Este archivo no comprueba autenticidad ni pagos bancarios.",
            workbook.add_format({
                "text_wrap": True, "valign": "top",
                "font_color": "#48556B",
            }),
        )
        if alertas:
            incidencias = workbook.add_worksheet("Revisar")
            incidencias.set_column(0, 0, 52)
            incidencias.set_column(1, 1, 86)
            incidencias.write_row(
                0, 0, ["Archivo", "Motivo de revisión"], encabezado
            )
            for j, alerta in enumerate(alertas, start=1):
                incidencias.write_string(j, 0, str(alerta.get("archivo", "")))
                incidencias.write_string(j, 1, str(alerta.get("detalle", "")))
            incidencias.freeze_panes(1, 0)
            incidencias.autofilter(0, 0, len(alertas), 1)
    finally:
        workbook.close()
    return memoria.getvalue()
