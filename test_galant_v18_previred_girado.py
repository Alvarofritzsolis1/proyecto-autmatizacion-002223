"""GALANT v18: regresiones OCR de Previred girado (solo datos sintéticos)."""
from __future__ import annotations

import fitz
import pandas as pd
from PIL import Image
from unittest.mock import patch

from previred_scan_adaptativo import (
    Anexo, _numero, _tipo, _filas, _columnas, extraer_previred_scan_adaptativo
)
from auditoria_laboral import leer_archivo


def test_clasifica_las_cuatro_instituciones():
    assert _tipo("SEGURO SOCIAL PREVISIONAL DETALLE") == "seguro_social"
    assert _tipo("ANEXOS DE DETALLE FONASA") == "salud"
    assert _tipo("ASOCIACION CHILENA DE SEGURIDAD ACHS DETALLE") == "mutual"
    assert _tipo("AFP HABITAT DETALLE DE PAGO") == "afp"
    assert _tipo("DOCUMENTO DESCONOCIDO") == ""


def test_montos_no_se_inventan_si_ocr_es_ambiguo():
    assert _numero("230.648") == 230648
    assert _numero("270834") == 270834
    assert _numero("2O0-?") is None
    assert _numero("") is None


def test_tabla_geometrica_sintetica():
    from PIL import ImageDraw
    # Los separadores se buscan en pixeles, no por el nombre del archivo.
    im = Image.new("L", (2000, 1200), 255)
    draw = ImageDraw.Draw(im)
    y0, y1 = 240, 330
    for y in (y0, y0+18, y0+36, y0+54, y0+72, y1):
        draw.line((20, y, 1970, y), fill=0, width=2)
    for x in range(20, 1971, 100):
        draw.line((x, y0, x, y1), fill=0, width=2)
    rows = _filas(im)
    assert len(rows) >= 3
    cols = _columnas(im, rows)
    assert len(cols) >= 9


def test_llevar_lector_adaptativo_antes_del_fallback():
    pdf = fitz.open()
    pdf.new_page()
    contenido = pdf.tobytes()
    pdf.close()
    expected = pd.DataFrame([{
        "periodo_remuneracion": "2026-09",
        "trabajador_rut": "100000008", "renta_imponible_salud": 200000
    }])
    with patch(
        "previred_scan_adaptativo.extraer_previred_scan_adaptativo",
        return_value=expected
    ) as adaptativo, patch(
        "previred_scan_fast.extraer_previred_escaneado_rapido",
        side_effect=AssertionError("No debería usar el OCR antiguo")
    ):
        resultado = leer_archivo(contenido, "archivo_escaneado.pdf")
    assert resultado.equals(expected)
    adaptativo.assert_called_once()


def test_afp_cero_no_reemplazada_por_cesantia():
    pdf = fitz.open()
    pdf.new_page()
    pdfbytes = pdf.tobytes()
    pdf.close()
    imagen = Image.new("L", (1100, 400), 255)
    anexos = [
        Anexo(tipo, i+1, imagen, [(240,260), (260,280)],
              list(range(20))*13, "2026-09", str(i))
        for i, tipo in enumerate(("salud", "afp", "mutual", "seguro_social"))
    ]
    ruts = ("100000008", "111111111")
    def fila(anexo, i):
        base = 200000 + i*10000
        return {
            "pagina": anexo.pagina, "tipo": anexo.tipo,
            "ruts": [ruts[i], ruts[i]],
            "bases": [0, 0] if anexo.tipo == "afp" and i == 0
                     else [base, base],
            "dias": [10, 10] if anexo.tipo in ("salud", "seguro_social")
                    else [],
            "cesantia": [base, base] if anexo.tipo == "afp" else [],
            "nombre": ("PERSONA PRUEBA UNO" if i == 0 else
                       "PERSONA PRUEBA DOS") if anexo.tipo == "salud" else "",
        }

    def header(*args, **kwargs):
        return "NOMBRE EMPRESA DE PRUEBA LIMITADA RUT 12.345.678-5"

    with patch("previred_scan_adaptativo._anexos", return_value=(anexos, [])), \
         patch("previred_scan_adaptativo._leer_fila", side_effect=fila), \
         patch("previred_scan_adaptativo._ocr", side_effect=header):
        result = extraer_previred_scan_adaptativo(pdfbytes, "sintetico.pdf")
    assert result is not None
    assert len(result) == 2
    assert result.iloc[0]["renta_imponible_afp"] == 0
    assert result.iloc[0]["renta_imponible_salud"] == 200000
    assert "Cesantía" in result.iloc[0]["__conflicto_pdf"]
    assert result.iloc[0]["dias_reales_pagados"] == 10
    assert result.iloc[1]["renta_imponible_afp"] == 210000
    assert result.attrs["diagnostico_ocr"]["paginas_detectadas"] == [1,2,3,4]
