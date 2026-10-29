"""Casos sintéticos: jamás subir PDF de trabajadores reales a GitHub."""
from types import SimpleNamespace
import numpy as np
import fitz

from rapidocr_pago import (
    _fecha_cuadro, _periodo_casillas, _unir, _lineas, rescatar
)
from pago_documental import analizar_pago_pdf


def linea(texto, x, y, confianza=.94):
    return {
        "texto": texto, "x": x, "y": y,
        "x_fin": min(x + .18, 1.0), "y_fin": min(y + .02, 1.0),
        "confianza": confianza,
    }


def test_rapidocr_fecha_del_recuadro_no_fecha_declaracion():
    datos = [
        linea("Fecha declaracion 19/10/2026", .12, .12),
        linea("Pago Electrónico", .72, .38),
        linea("13/10/2026", .73, .41),
        linea("19/10/2026", .08, .43),
    ]
    assert _fecha_cuadro(datos) == "13/10/2026"


def test_rapidocr_periodo_dos_casillas_mes_ano():
    datos = [
        linea("PERIODO", .62, .32),
        linea("MES", .47, .34),
        linea("AÑO", .52, .34),
        linea("09", .48, .37),
        linea("2026", .53, .37),
        linea("Fecha movimiento 15/10/2026", .7, .69),
    ]
    assert _periodo_casillas(datos) == "2026-09"


def test_rapidocr_sin_periodo_de_movimiento():
    datos = [
        linea("INICIO", .60, .32),
        linea("09", .48, .37),
        linea("2026", .53, .37),
    ]
    assert _periodo_casillas(datos) == ""


def test_conflicto_folio_bloquea_mezcla():
    actual = {
        "pagina": 1, "folio": "2006260901492723",
        "institucion": "AFP Planvital",
        "periodo": "", "fecha_pago": "",
        "estado": "EVIDENCIA_INSUFICIENTE",
    }
    nuevo = {
        "folio": "2006260901492724",
        "institucion": "AFP Planvital",
        "periodo": "2026-09",
        "fecha_pago": "13/10/2026",
        "cuadro_pago": True, "plantilla": True,
    }
    _unir(actual, nuevo)
    assert actual["folio"] == "2006260901492723"
    assert actual["periodo"] == ""
    assert actual["fecha_pago"] == ""
    assert actual["conflicto_folio_rapidocr"] is True


def test_conflicto_fecha_no_sobrescribe_tesseract():
    actual = {
        "pagina": 1, "folio": "2006260901492723",
        "institucion": "AFP Planvital",
        "periodo": "2026-09", "fecha_pago": "19/10/2026",
        "estado": "PAGO_RESPALDADO_EN_DOCUMENTO",
    }
    nuevo = {
        "folio": "2006260901492723",
        "institucion": "AFP Planvital",
        "periodo": "2026-09",
        "fecha_pago": "13/10/2026",
        "cuadro_pago": True, "plantilla": True,
    }
    _unir(actual, nuevo)
    assert actual["fecha_pago"] == "19/10/2026"
    assert actual["estado"] == "EVIDENCIA_INSUFICIENTE"
    assert actual["conflicto_fecha_pago_rapidocr"] is True


def test_rapidocr_sin_folio_comun_requiere_revision():
    actual = {
        "pagina":1, "folio":"2006260901492723",
        "institucion":"AFP Planvital", "periodo":"",
        "fecha_pago":"", "estado":"PAGO_RESPALDADO_EN_DOCUMENTO",
    }
    nuevo = {
        "folio":"", "institucion":"AFP Planvital",
        "periodo":"2026-09", "fecha_pago":"13/10/2026",
        "cuadro_pago":True, "plantilla":True,
    }
    _unir(actual, nuevo)
    assert actual["rapidocr_folio_no_corrobado"] is True
    assert actual["estado"] == "EVIDENCIA_INSUFICIENTE"


def test_arrays_numpy_oficiales_rapidocr():
    result=SimpleNamespace(
        txts=np.array(["PREVIRED", "Pago Electronico"],dtype=object),
        scores=np.array([.98,.99]),
        boxes=np.array([
            [[4,4],[80,4],[80,18],[4,18]],
            [[5,34],[92,34],[92,50],[5,50]],
        ]),
    )
    salida=_lineas(result,100,100)
    assert [x["texto"] for x in salida]==["PREVIRED","Pago Electronico"]


def test_rescate_limited_to_two_scanned_pages_without_models():
    doc=fitz.open()
    for _ in range(5):
        doc.new_page(width=800,height=600)
    data=doc.tobytes()
    doc.close()
    class Fake:
        def __init__(self):
            self.calls=0
        def __call__(self,img):
            self.calls+=1
            return SimpleNamespace(txts=[],scores=[],boxes=[])
    engine=Fake()
    evidencias=[]
    estado=rescatar(data,evidencias,max_paginas=2,engine=engine)
    assert estado["paginas"]==[1,3]
    assert engine.calls<=4
    assert len(evidencias)==0


def test_no_rapidocr_on_fully_digital_pdf():
    doc=fitz.open()
    pagina=doc.new_page(width=842,height=595)
    textos=[
        "COMPROBANTE DE PAGO DE COTIZACIONES PREVISIONALES",
        "PREVIRED", "Numero de folio: 2006260901492723",
        "AFP Planvital", "Periodo 09/2026",
        "Pago Electronico", "13/10/2026",
    ]
    for i,t in enumerate(textos):
        pagina.insert_text((40,50+i*24),t)
    data=doc.tobytes()
    doc.close()
    resultado=analizar_pago_pdf(data,"ficticio.pdf",usar_rapidocr=True)
    assert resultado["paginas_imagen"]==0
    assert resultado["rapidocr"]["estado"]=="deshabilitado"
    assert resultado["comprobantes"]
