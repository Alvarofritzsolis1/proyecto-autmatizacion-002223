"""Tests OCR alternativo: ninguna llamada real a Google Vision ni PDF privado."""
from __future__ import annotations

import fitz
from worker import vision_rescue


def _documento():
    p = fitz.open()
    page = p.new_page()
    page.insert_text((35,55),"SIMULACION DE COMPROBANTE")
    b = p.tobytes()
    p.close()
    return b


def _info(recibos=None, paginas=1, escaneadas=1):
    return {
        "paginas": paginas, "paginas_imagen": escaneadas,
        "revision_integral": False,
        "comprobantes": recibos if recibos is not None else [],
    }


def test_no_vision_sin_consentimiento_explicito(monkeypatch):
    monkeypatch.delenv("GALANT_VISION_ENABLED", raising=False)
    recibos = [{"pagina":1,"periodo":"","folio":""}]
    final = vision_rescue.rescatar_con_vision(_documento(), _info(recibos), None)
    assert final["vision_estado"] == "deshabilitado"
    assert final["vision_paginas"] == []


def test_no_costes_en_pdf_digital(monkeypatch):
    monkeypatch.setenv("GALANT_VISION_ENABLED","true")
    monkeypatch.setattr(vision_rescue,"_reservar_unidad",lambda c: (_ for _ in ()).throw(AssertionError("No llamar a Vision")))
    final = vision_rescue.rescatar_con_vision(_documento(), _info([],1,0), None)
    assert final["vision_estado"] == "no_necesario"


def test_rechazar_fecha_de_folio_diferente():
    base = [{
        "pagina":1, "institucion":"AFP Modelo",
        "folio":"2006260901492723", "periodo":"", "fecha_pago":"",
        "estado":"EVIDENCIA_INSUFICIENTE"
    }]
    nuevo = {
        "pagina":1, "institucion":"AFP Modelo",
        "folio":"2016260901492723", "periodo":"2026-09",
        "fecha_pago":"13/10/2026"
    }
    assert vision_rescue._combinar_con_precaucion(base,nuevo) is False
    assert base[0]["periodo"] == ""
    assert base[0]["fecha_pago"] == ""
    assert base[0]["conflicto_folio_ocr"] is True


def test_rescatar_campos_del_mismo_folio():
    base = [{
        "pagina":1,"folio":"2006260901492723",
        "institucion":"Institución no identificada","periodo":"",
        "fecha_pago":"","estado":"EVIDENCIA_INSUFICIENTE"
    }]
    nuevo = {
        "pagina":1,"folio":"2006260901492723",
        "institucion":"AFP Planvital","periodo":"2026-09",
        "fecha_pago":"13/10/2026","estado":"PAGO_RESPALDADO_EN_DOCUMENTO"
    }
    assert vision_rescue._combinar_con_precaucion(base,nuevo)
    assert base[0]["periodo"] == "2026-09"
    assert base[0]["fecha_pago"] == "13/10/2026"
    assert base[0]["fuente_rescate"].startswith("Google Vision")
    # No convertir el registro a aprobado automáticamente.
    assert base[0]["estado"] == "EVIDENCIA_INSUFICIENTE"


def test_no_completar_si_hay_dos_instituciones_en_una_pagina():
    recibos = [
        {"pagina":1,"institucion":"AFP Modelo","folio":"111111111111","fecha_pago":""},
        {"pagina":1,"institucion":"Fonasa","folio":"222222222222","fecha_pago":""},
    ]
    otro = {"pagina":1,"folio":"222222222222","fecha_pago":"13/10/2026"}
    assert vision_rescue._combinar_con_precaucion(recibos,otro) is False
    assert all(not r["fecha_pago"] for r in recibos)


def test_cuota_no_verificable_no_envia_documentos(monkeypatch):
    monkeypatch.setenv("GALANT_VISION_ENABLED","true")
    monkeypatch.setattr(vision_rescue,"_reservar_unidad",lambda c: (_ for _ in ()).throw(OSError("Privado")))
    monkeypatch.setattr(vision_rescue,"_texto_google_vision",lambda *args,**kwargs: (_ for _ in ()).throw(AssertionError("No llamar")))
    f=vision_rescue.rescatar_con_vision(
        _documento(),
        _info([{"pagina":1,"folio":"111111111111","periodo":""}]),
        object()
    )
    assert f["vision_paginas"] == []
    assert f["vision_estado"] == "sin_cuota_verificable"


def test_cuota_agotada_no_envia_paginas(monkeypatch):
    monkeypatch.setenv("GALANT_VISION_ENABLED","true")
    monkeypatch.setattr(vision_rescue,"_reservar_unidad",lambda c: False)
    monkeypatch.setattr(vision_rescue,"_texto_google_vision",lambda *args,**kwargs: (_ for _ in ()).throw(AssertionError("No llamar")))
    f=vision_rescue.rescatar_con_vision(
        _documento(), _info([{"pagina":1,"periodo":""}]), object()
    )
    assert f["vision_cuota_agotada"] is True
    assert f["vision_paginas"] == []


def test_vision_extrae_solo_dos_paginas(monkeypatch):
    monkeypatch.setenv("GALANT_VISION_ENABLED","true")
    monkeypatch.setenv("GALANT_VISION_MAX_PAGINAS_PDF","2")
    llamadas=[]
    monkeypatch.setattr(vision_rescue,"_reservar_unidad",lambda c: True)
    def simulacion(*args, **kwargs):
        llamadas.append(True)
        return "sin comprobante identificable"
    monkeypatch.setattr(vision_rescue,"_texto_google_vision",simulacion)
    doc=fitz.open()
    for _ in range(5):doc.new_page()
    pdf=doc.tobytes()
    doc.close()
    recibos=[{"pagina":n,"periodo":""} for n in range(1,6)]
    f=vision_rescue.rescatar_con_vision(pdf,_info(recibos,5,5),object())
    assert len(llamadas)==2
    assert f["vision_paginas"]==[1,2]
    assert f["revision_integral"] is False


def test_env_limits_are_capped(monkeypatch):
    monkeypatch.setenv("GALANT_VISION_MAX_MES","20000")
    monkeypatch.setenv("GALANT_VISION_MAX_DIA","200")
    assert vision_rescue._entero_env("GALANT_VISION_MAX_MES",300,0,900)==900
    assert vision_rescue._entero_env("GALANT_VISION_MAX_DIA",20,0,30)==30
