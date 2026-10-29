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

def test_classifier_previred_digital_without_trusting_filename():
    import fitz
    from f301_lector import _es_previred_rapido
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text(
        (40, 50),
        "PLANILLA DE DECLARACION Y PAGO SIMULTANEO DE OBLIGACIONES PREVISIONALES"
    )
    page.insert_text((40, 75), "Previred - periodo 09/2026, pago electronico 10/10/2026")
    page.insert_text((40, 95), "Numero de folio 2017260900656295")
    page.insert_text((40, 115), "Total de cotizaciones acreditadas en documento")
    assert _es_previred_rapido(page) is True
    doc.close()


def test_classifier_does_not_reject_f301_by_generic_cotizaciones_word():
    import fitz
    from f301_lector import _es_previred_rapido
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((40, 50), "CERTIFICADO DE CUMPLIMIENTO")
    page.insert_text((40, 75), "OBLIGACIONES LABORALES Y PREVISIONALES")
    page.insert_text((40, 95), "Contiene cotizaciones previsionales y trabajadores declarados.")
    page.insert_text((40, 115), "El empleador declara cumplimiento de sus obligaciones.")
    assert _es_previred_rapido(page) is False
    doc.close()


def test_periodo_en_casillas_separadas_con_etiqueta_a_la_derecha():
    """Imagen de GALANT: PERIODO x=0.62, MES 09 x=0.48, AÑO x=0.51."""
    from pago_documental import _periodo_espacial
    d = {
        "text": ["PERIODO", "09", "2026", "INICIO", "15", "09", "2026"],
        "left": [620, 487, 513, 750, 755, 790, 830],
        "top": [322, 369, 369, 520, 545, 545, 545],
        "conf": [92, 86, 86, 80, 80, 80, 80],
    }
    assert _periodo_espacial(d, 1000, 1000) == "2026-09"


def test_ocr_periodo_intercalado_en_afp_planvital():
    from pago_documental import _periodo
    assert _periodo("Periodo\nRetroactivo\n09/2026\nFecha Pago\n13/10/2026") == "2026-09"
    assert _periodo("Perlodo de Remuneraciones: 09/2026") == "2026-09"


def test_ocr_fecha_pago_electronico_sin_palabra_pago():
    from pago_documental import _fecha_espacial
    d = {
        "text": ["Comprobante", "Electrénico", "13/10/2026", "PREVIRED"],
        "left": [20, 827, 815, 830],
        "top": [65, 398, 424, 448],
        "conf": [90, 86, 91, 95],
    }
    assert _fecha_espacial(d, 1000, 1000) == "13/10/2026"


def test_ocr_periodo_sin_confundir_fechas_de_movimientos():
    from pago_documental import _periodo_espacial
    d = {
        "text": ["DIA", "MES", "AÑO", "09", "2026", "15", "09", "2026"],
        "left": [600, 700, 800, 790, 830, 700, 790, 830],
        "top": [340, 340, 340, 390, 390, 412, 412, 412],
        "conf": [90] * 8,
    }
    assert _periodo_espacial(d, 1000, 1000) == ""


def test_ocr_fecha_declaracion_no_equivale_a_fecha_pago():
    from pago_documental import _fecha_pago
    assert _fecha_pago("Fecha Declaración: 10/10/2026") == ""
    texto = (
        "Pago Electrénico\nPeriodo de Remuneraciones: 09/2026\n"
        "Número de Folio: 2006260901492723\n13/10/2026\n10:47 PM"
    )
    assert _fecha_pago(texto) == "13/10/2026"
