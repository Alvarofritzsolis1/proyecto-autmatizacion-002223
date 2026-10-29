"""Regresiones sintéticas: nunca publicar PDF laborales reales en GitHub."""
import fitz
from pago_documental import analizar_pago_pdf, _periodo, _fecha_pago

def _pdf(lines):
    doc = fitz.open()
    pag = doc.new_page(width=842, height=595)
    for i, line in enumerate(lines):
        pag.insert_text((30, 40 + 22*i), line, fontsize=10)
    data = doc.tobytes()
    doc.close()
    return data

def test_fechas_separadas_del_periodo():
    assert _periodo("Periodo 09/2026") == "2026-09"
    assert _periodo("Periodo Septiembre 2026") == "2026-09"
    assert _fecha_pago("Fecha Declaracion: 01/10/2026\nFecha Pago: 20/10/2026") == "20/10/2026"
    assert _fecha_pago("Fecha Declaracion: 01/10/2026") == ""

def test_pago_documentado_independiente_de_nomina():
    pdf = _pdf([
        "COMPROBANTE DE PAGO DE COTIZACIONES PREVISIONALES",
        "AFP Modelo",
        "Numero de Folio: 2009202609457509",
        "Periodo 09/2026",
        "Pago Electronico",
        "13/10/2026",
        "PREVIRED",
    ])
    r=analizar_pago_pdf(pdf,"simulado.pdf")
    assert r["revision_integral"] is True
    assert len(r["comprobantes"]) == 1
    c=r["comprobantes"][0]
    assert c["periodo"] == "2026-09"
    assert c["fecha_pago"] == "13/10/2026"
    assert c["estado"] == "PAGO_RESPALDADO_EN_DOCUMENTO"

def test_no_pago_sin_fecha_no_es_pago_confirmado():
    pdf = _pdf([
        "COMPROBANTE DE DECLARACION Y NO PAGO DE COTIZACIONES PREVISIONALES",
        "AFP Provida",
        "Periodo 09/2026",
        "PREVIRED",
    ])
    e=analizar_pago_pdf(pdf,"ejemplo.pdf")["comprobantes"][0]
    assert e["fecha_pago"] == ""
    assert e["estado"] == "DECLARACION_SIN_PAGO_IDENTIFICADO"

def test_posterior_regularizacion_no_es_impago_automatico():
    pdf = _pdf([
        "COMPROBANTE DE DECLARACION Y NO PAGO DE COTIZACIONES PREVISIONALES",
        "AFP Habitat",
        "Periodo 09/2026",
        "Fecha Declaracion: 01/10/2026",
        "Fecha Pago: 20/10/2026",
        "Pago Electronico",
        "PREVIRED",
    ])
    e=analizar_pago_pdf(pdf,"ejemplo.pdf")["comprobantes"][0]
    assert e["estado"] == "PAGO_POSTERIOR_DOCUMENTADO_REVISAR"

def test_fonasa_opciones_sin_marcar_no_implican_impago():
    pdf=_pdf([
        "PLANILLA DE DECLARACION Y PAGO SIMULTANEO DE OBLIGACIONES PREVISIONALES",
        "Fonasa",
        "Declaracion y Pago",
        "Declaracion y No Pago",
        "Periodo 09/2026",
        "Pago Electronico",
        "13/10/2026",
        "PREVIRED",
    ])
    e=analizar_pago_pdf(pdf,"ejemplo.pdf")["comprobantes"][0]
    assert e["estado"] == "PAGO_RESPALDADO_EN_DOCUMENTO"

def test_documento_nominal_f30_no_es_f301_por_nombre():
    from f301_lector import es_f301
    pdf=_pdf([
        "COMPROBANTE DE PAGO DE COTIZACIONES PREVISIONALES",
        "PREVIRED",
        "Pago Electronico",
        "13/10/2026",
        "Periodo 09/2026",
    ])
    assert es_f301(pdf,"contratista_F30.pdf") is False

def test_ocr_misspelling_electronico_is_still_document_candidate():
    from pago_documental import _interpretar
    text = (
        "DETALLE DE PAGO DE COTIZACIONES PREVISIONALES "
        "Numero de Folio: 2006260700834385 "
        "Periodo de Remuneraciones: 07/2026 "
        "Pago Electrénico 06/08/2026 PREVIRED"
    )
    found = _interpretar(text, 1, "OCR")
    assert found is not None
    assert found["periodo"] == "2026-07"
    # La etiqueta mal escrita no puede ocultar el documento, pero el pago
    # sigue necesitando validación independiente de la fecha.
    assert found["folio"] == "2006260700834385"


def test_no_inferir_pago_desde_fecha_declaracion():
    from pago_documental import _interpretar
    text = (
        "COMPROBANTE DE DECLARACION Y NO PAGO "
        "DE COTIZACIONES PREVISIONALES PREVIRED "
        "Numero de Folio: 2005202609547098 "
        "Periodo 09/2026 "
        "Fecha Declaracion: 01/10/2026"
    )
    found = _interpretar(text, 1, "PDF")
    assert found["fecha_pago"] == ""
    assert found["estado"] == "DECLARACION_SIN_PAGO_IDENTIFICADO"


def test_periodo_no_se_toma_de_fecha_pago():
    from pago_documental import _periodo
    text = "Pago Electronico 20/10/2026, Periodo de Remuneraciones: 09/2026"
    assert _periodo(text) == "2026-09"
