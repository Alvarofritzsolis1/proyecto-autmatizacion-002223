"""Pruebas sintéticas: nunca incorporar certificados reales al GitHub público."""
from __future__ import annotations

import fitz
from f301_lector import (
    analizar_f301, es_f301, rut_valido, _nomina_en_texto, _pago_resumen
)


def _pdf_dos_paginas():
    doc = fitz.open()
    hoja = doc.new_page()
    hoja.insert_text((35, 40),
        "Certificado de Cumplimiento de Obligaciones Laborales y Previsionales\n"
        "N° Certificado: 2000/2026/12345678\n"
        "1.1 - Antecedentes Empleador (solicitante)\n"
        "Nombre o Razon Social RUT\n"
        "EMPRESA SINTETICA SPA 12.345.678-5\n"
        "Representante Legal RUT Representante Legal\n"
        "1.2 - Empresa Principal\n"
        "Nombre o Razon Social RUT\n"
        "EMPRESA PRINCIPAL SPA 12.345.678-5\n"
        "Representante Legal\n"
        "2 - Obra / Faena / Servicio\n")
    hoja = doc.new_page()
    hoja.insert_text((35, 40),
        "Certificado de Cumplimiento de Obligaciones Laborales y Previsionales\n"
        "N° Certificado: 2000/2026/12345678\n"
        "Trabajadores declarados en la Certificacion\n"
        "Detalle por Periodo\n"
        "Septiembre 2026\n"
        "N° RUT Nombre Trabajador\n"
        "1 10.000.000-8 Persona Primera Ejemplo\n"
        "2 11.111.111-1 Persona Segunda Ejemplo\n"
        "Total Trabajadores 2\n")
    data = doc.tobytes()
    doc.close()
    return data


def test_detectar_f30_por_contenido_sin_nombre():
    assert es_f301(_pdf_dos_paginas(), "documento_sin_nombre.pdf")


def test_f30_sin_resumen_no_es_pago_acreditado():
    certificados, nomina, incidencias = analizar_f301(
        [(_pdf_dos_paginas(), "documento_sin_nombre.pdf")]
    )
    assert len(certificados) == 1
    cert = certificados[0]
    assert cert["folio"] == "2000/2026/12345678"
    assert cert["rut_contratista"] == "123456785"
    assert cert["periodo"] == "2026-09"
    assert cert["trabajadores_declarados"] == 2
    assert cert["trabajadores_identificados"] == 2
    assert cert["cotizaciones"] == "SIN_RESUMEN_NO_SE_PUEDE_CONFIRMAR"
    assert len(nomina) == 2
    assert all(r["trabajador_rut"] for r in nomina)
    assert any("Falta página de resumen" in a["detalle"] for a in incidencias)


def test_rechazar_rut_dv_incorrecto():
    assert rut_valido("12.345.678-9") == ""
    assert rut_valido("12.345.678-5") == "123456785"


def test_nomina_dos_rut_validos_no_necesita_inventar_datos():
    texto = (
        "Trabajadores declarados en la Certificacion\n"
        "Detalle por Periodo\nSeptiembre 2026\n"
        "N° RUT Nombre Trabajador\n"
        "1 10.000.000-8 Persona Primera Ejemplo\n"
        "2 11.111.111-1 Persona Segunda Ejemplo\n"
        "Total Trabajadores 2"
    )
    nomina, total, mes = _nomina_en_texto(texto)
    assert total == 2 and mes == "2026-09"
    assert len(nomina) == 2


def test_declaracion_de_pago_es_solo_del_pdf():
    assert _pago_resumen(
        "Cotizaciones Previsionales\nPagadas\nAdjunta Nomina\nSi\nNo"
    ) == "SI_DECLARADO_EN_PDF"
    assert _pago_resumen("No hay resumen de pago") == "NO_LEIBLE"


def test_rechazar_archivo_que_no_es_pdf():
    assert not es_f301(b"No es un PDF", "datos.csv")
