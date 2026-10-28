"""Pruebas de GALANT v17 sin documentos laborales reales en GitHub."""
from __future__ import annotations
from io import BytesIO
from types import SimpleNamespace
from zipfile import ZipFile

import pandas as pd
from PIL import Image

from bandeja_revision import generar_bandeja, resumen_calidad
from informe_galant import informe_consolidado
from f301_lector import _pagina_texto, _puntos_f301


def _certificado(**cambios):
    c = {
        "archivo": "sintetico_F30.pdf", "folio": "2000/2026/11111111",
        "contratista": "EMPRESA FICTICIA", "rut_contratista": "123456785",
        "periodo": "2026-09", "paginas": "1, 2", "trabajadores_declarados": 3,
        "trabajadores_identificados": 2,
        "cotizaciones": "SIN_RESUMEN_NO_SE_PUEDE_CONFIRMAR",
    }
    c.update(cambios)
    return c


def test_f301_nomina_incompleta_tiene_prioridad_alta_y_evidencia():
    bandeja = generar_bandeja(certificados=[_certificado()])
    importante = bandeja.loc[bandeja["prioridad"].eq("ALTA")]
    assert len(importante) == 1
    assert "2 de 3" in importante.iloc[0]["hallazgo"]
    assert importante.iloc[0]["pagina"] == "1, 2"
    assert importante.iloc[0]["archivo"] == "sintetico_F30.pdf"


def test_f301_sin_resumen_no_se_marca_impago():
    bandeja = generar_bandeja(certificados=[_certificado(
        trabajadores_declarados=2, trabajadores_identificados=2
    )])
    assert len(bandeja) == 1
    assert bandeja.iloc[0]["prioridad"] == "MEDIA"
    assert "Falta el resumen" in bandeja.iloc[0]["hallazgo"]
    assert "impago" in bandeja.iloc[0]["accion_recomendada"].lower()


def test_f301_que_declara_pago_y_nomina_completa_no_crea_alerta():
    bandeja = generar_bandeja(certificados=[_certificado(
        trabajadores_declarados=2, trabajadores_identificados=2,
        cotizaciones="SI_DECLARADO_EN_PDF"
    )])
    assert bandeja.empty


def test_diferencia_previred_conserva_rut_archivo_y_pagina():
    detalle = pd.DataFrame([{
        "archivo_origen": "cotizaciones.pdf", "hoja_o_pagina": "p.6",
        "contratista_nombre": "EMPRESA FICTICIA",
        "periodo_remuneracion": "2026-09", "trabajador_rut": "100000008",
        "estado_auditoria": "ALERTA_DESCUADRE_RENTAS",
        "motivo_revision": "Diferencia entre bases imponibles: AFP 100 y Salud 200"
    }])
    bandeja = generar_bandeja(detalle=detalle)
    assert bandeja.iloc[0]["prioridad"] == "ALTA"
    assert bandeja.iloc[0]["rut_trabajador"] == "100000008"
    assert bandeja.iloc[0]["pagina"] == "p.6"
    assert "Comparar" in bandeja.iloc[0]["accion_recomendada"]


def test_no_duplica_error_f301_del_resumen():
    c = _certificado()
    bandeja = generar_bandeja(
        certificados=[c],
        incidencias=[{
            "archivo": c["archivo"], "folio": c["folio"],
            "detalle": "Falta página de resumen: no se puede confirmar pago"
        }]
    )
    assert len(bandeja) == 2


def test_no_repite_todos_los_ruts_si_falta_previred():
    cruce = pd.DataFrame([{
        "archivo": "f301.pdf", "certificado": "2000/2026/12345678",
        "contratista": "EMPRESA FICTICIA", "periodo": "2026-09",
        "resultado": "SIN_COMPROBANTE_COMPARABLE",
        "accion": "Subir Previred septiembre."
    }])
    detalle = pd.DataFrame([
        {"resultado": "SIN_PREVIRED_MISMO_PERIODO", "rut_trabajador": str(i)}
        for i in range(20)
    ])
    bandeja = generar_bandeja(cruce_resumen=cruce, cruce_detalle=detalle)
    assert len(bandeja) == 1
    assert "No hay cotizaciones comparables" in bandeja.iloc[0]["hallazgo"]


def test_registro_cotejado_sin_error_no_se_muestra():
    tabla = pd.DataFrame([{
        "resultado": "RUT_COINCIDE", "rut_trabajador": "100000008"
    }])
    assert generar_bandeja(cruce_detalle=tabla).empty


def test_error_archivo_y_duplicado_tienen_prioridades_distintas():
    log = pd.DataFrame([{"archivo": "incompleto.pdf", "resultado": "ERROR",
                         "detalle": "Archivo ilegible"}])
    bandeja = generar_bandeja(
        log=log, duplicados=[("igual.pdf", "original.pdf")])
    assert bandeja["prioridad"].tolist() == ["ALTA", "BAJA"]


def test_orden_prioridades_y_resumen_sin_porcentaje_ficticio():
    c = _certificado()
    bandeja = generar_bandeja(certificados=[c],
                              duplicados=[("igual.pdf", "orig.pdf")])
    resumen = resumen_calidad([c], pd.DataFrame([
        {"estado_auditoria": "CONFORME"},
        {"estado_auditoria": "REVISAR_DATOS"},
    ]), bandeja)
    assert resumen["nominas_completas"] == 0
    assert resumen["pendientes_prioridad_alta"] == 1
    assert resumen["filas_con_observacion"] == 1
    assert "confianza_pct" not in resumen


def test_reporte_excel_valido_y_sin_formulas_inyectadas():
    cert = _certificado(contratista="=2+2")
    bandeja = generar_bandeja(certificados=[cert])
    blob = informe_consolidado(
        bandeja=bandeja, certificados=[cert], matriz=pd.DataFrame(),
        detalle_cruce=pd.DataFrame(), resumen_cruce=pd.DataFrame(),
        log=pd.DataFrame(),
    )
    assert blob.startswith(b"PK")
    with ZipFile(BytesIO(blob)) as z:
        assert z.testzip() is None
        workbook = z.read("xl/workbook.xml").decode("utf-8")
        assert "Bandeja_Revision" in workbook
        assert "Certificados_F301" in workbook
        sheet_contents = "\n".join(
            z.read(n).decode("utf-8") for n in z.namelist()
            if n.startswith("xl/worksheets/sheet")
        )
        assert "<f>" not in sheet_contents


def test_ocr_indicadores_documentales_sin_inventar_confianza():
    assert _puntos_f301("Certificado de cumplimiento de obligaciones laborales y previsionales") >= 3
    assert _puntos_f301("456 123 888 zzz") == 0


def test_reintento_de_giro_con_ocr_solo_si_no_lee_estructura(monkeypatch):
    import pytesseract
    from unittest.mock import Mock

    imagen = Image.new("RGB", (60, 80), "white")
    pagina = Mock()
    pagina.get_text.return_value = ""
    pagina.get_pixmap.return_value = SimpleNamespace(
        width=60, height=80, samples=imagen.tobytes()
    )
    respuestas = iter([
        "XX-- ###",  # Primera lectura mal orientada
        "texto ilegible",  # Segundo modo OCR, todavía incorrecto
        "Certificado de cumplimiento de obligaciones laborales y previsionales"
    ])
    monkeypatch.setattr(
        pytesseract, "image_to_string",
        lambda *args, **kwargs: next(respuestas)
    )
    monkeypatch.setattr(
        pytesseract, "image_to_osd",
        lambda *args, **kwargs: {"rotate": 90}
    )
    texto, origen = _pagina_texto(pagina)
    assert "Certificado de cumplimiento" in texto
    assert origen == "OCR"


def test_no_usa_ocr_si_texto_digital_es_suficiente(monkeypatch):
    from unittest.mock import Mock
    import pytesseract

    monkeypatch.setattr(pytesseract, "image_to_string",
                        lambda *args, **kw: (_ for _ in ()).throw(
                            AssertionError("OCR no debería ejecutarse")
                        ))
    pagina = Mock()
    pagina.get_text.return_value = (
        "Certificado de cumplimiento de obligaciones laborales. "
        "Información por empresa, trabajadores y periodo. " * 4
    )
    texto, tipo = _pagina_texto(pagina)
    assert tipo == "DIGITAL"
