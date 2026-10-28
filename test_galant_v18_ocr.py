"""Regresiones GALANT v18: OCR Previred girado sin documentos privados."""
import io
from unittest.mock import patch
import fitz
import pandas as pd
import numpy as np
from PIL import Image

from auditoria_laboral import leer_archivo
from previred_scan_adaptativo import (
    Anexo, _pagina_horizontal, _numeros_ocr, _resolver_rut,
    _filas_y, _columnas, extraer_previred_scan_adaptativo,
)


def _pdf_en_memoria():
    doc = fitz.open()
    doc.new_page(width=595, height=842)
    blob = doc.tobytes()
    doc.close()
    return blob


def test_ocr_adaptativo_antes_que_lector_rapido():
    resultado = pd.DataFrame([{
        "trabajador_rut": "100000008", "periodo_remuneracion": "2026-09"
    }])
    with patch(
        "previred_scan_adaptativo.extraer_previred_scan_adaptativo",
        return_value=resultado,
    ) as nuevo, patch(
        "previred_scan_fast.extraer_previred_escaneado_rapido",
        side_effect=AssertionError("Se ejecutó lector rígido innecesariamente"),
    ):
        obtenido = leer_archivo(_pdf_en_memoria(), "comprobante_rotado.pdf")
    assert len(obtenido) == 1
    assert nuevo.call_count == 1


def test_recuperar_anterior_lector_si_no_hay_formato_adaptativo():
    esperado = pd.DataFrame([{"trabajador_rut": "100000008"}])
    with patch(
        "previred_scan_adaptativo.extraer_previred_scan_adaptativo",
        return_value=None,
    ), patch(
        "previred_scan_fast.extraer_previred_escaneado_rapido",
        return_value=esperado,
    ) as anterior:
        resultado = leer_archivo(_pdf_en_memoria(), "otro_formato.pdf")
    assert anterior.called
    assert resultado.equals(esperado)


def test_separar_afp_fondo_cero_de_cesantia():
    imagen = Image.new("L", (1400, 800), 255)
    plantillas = [
        Anexo(t, p, imagen, [(220, 240)]*4, list(range(20)), "2026-09", "")
        for p, t in ((2, "seguro_social"), (4, "afp"), (8, "mutual"), (10, "salud"))
    ]
    ruts = ["100000008", "111111111", "222222222", "123456785"]
    bases = [230648, 270834, 230648, 230648]
    def obs(anexo, index):
        monto = bases[index]
        valor_afp = 0 if anexo.tipo == "afp" and index == 1 else monto
        return {
            "tipo": anexo.tipo, "pagina": anexo.pagina, "folio": "",
            "ruts": [ruts[index]], "bases": [valor_afp, valor_afp],
            "cesantia": [monto] if anexo.tipo == "afp" else [],
            "dias": [10] if anexo.tipo in ("salud", "seguro_social") else [],
            "nombre": "PERSONA SINTETICA EJEMPLO" if anexo.tipo == "salud" else "",
        }
    with patch("previred_scan_adaptativo._extraer_paginas",
               return_value=(plantillas, [])), patch(
        "previred_scan_adaptativo._observaciones", side_effect=obs
    ), patch(
        "previred_scan_adaptativo._lectura",
        return_value="NOMBRE EMPRESA SINTETICA LIMITADA RUT 76.543.210-3",
    ):
        salida = extraer_previred_scan_adaptativo(
            _pdf_en_memoria(), "planillas_sinteticas.pdf"
        )
    assert salida is not None and len(salida) == 4
    assert salida["trabajador_rut"].nunique() == 4
    assert salida["dias_reales_pagados"].tolist() == [10] * 4
    assert salida["renta_imponible_salud"].sum() == 962778
    assert salida["renta_imponible_mutual"].sum() == 962778
    assert salida["renta_imponible_afp"].sum() == 691944
    observado = salida.loc[salida["trabajador_rut"] == "111111111"].iloc[0]
    assert observado["renta_imponible_afp"] == 0
    assert "Seguro Cesantía 270834" in observado["__conflicto_pdf"]
    assert observado["__ocr_estado"] == "OCR_REQUIERE_REVISION"
    assert salida["periodo_remuneracion"].eq("2026-09").all()
    assert salida["contratista_rut"].eq("765432103").all()
    assert salida.attrs["diagnostico_ocr"]["paginas_detectadas"] == [2, 4, 8, 10]


def test_rut_se_recupera_solo_si_otro_anexo_confirma_dv():
    rut, cruzado = _resolver_rut(
        {"ruts": ["100000009"]}, {"100000008"}
    )
    assert (rut, cruzado) == ("100000008", True)
    rut_inseguro, _ = _resolver_rut(
        {"ruts": ["100000009"]}, {"100000008", "100000001"}
    )
    assert rut_inseguro == ""


def test_montos_no_se_inventan_cuando_ocr_ilegible():
    assert _numeros_ocr("") is None
    assert _numeros_ocr("abc") is None
    assert _numeros_ocr("1.2.3") is None
    assert _numeros_ocr("230.648") == 230648


def test_detector_geometrico_acepta_tabla_con_filas_variables():
    from PIL import ImageDraw
    im = Image.new("L", (1600, 800), 255)
    draw = ImageDraw.Draw(im)
    for y in (170, 190, 210, 230, 250):
        draw.line([(20, y), (1540, y)], fill=0, width=2)
    filas = _filas_y(im)
    assert len(filas) >= 3
    for x in (20, 120, 250, 400, 550, 700, 850, 1000, 1150, 1300, 1540):
        draw.line([(x, 170), (x, 250)], fill=0, width=2)
    assert len(_columnas(im, filas)) >= 9


def test_pagina_vertical_se_gira_para_leer_anexos_horizontales():
    class Pagina:
        def get_pixmap(self, **_kwargs):
            return type("Pixmap", (), {
                "width": 600, "height": 800,
                "samples": Image.new("L", (600, 800), 255).tobytes()
            })()
    img = _pagina_horizontal(Pagina())
    assert img.width == 800 and img.height == 600
