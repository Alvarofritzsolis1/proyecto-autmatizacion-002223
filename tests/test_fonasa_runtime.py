"""Regression tests for Streamlit hot-reload mismatch, using no private PDF.

The source code on disk can be newer than an imported Python module.
A naive checksum of Path(__file__) cannot establish what ran in memory.
"""
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import fonasa_nomina_simple as original
import fonasa_runtime as runtime


def test_real_import_contract_includes_worker_cell_trace():
    loaded = runtime.cargar_lector_fonasa()
    assert runtime._contrato_valido(loaded)
    info = runtime.estado_lector_fonasa()
    assert info["contrato_traza"] is True
    assert len(info["sha256_fuente_16"]) == 16
    assert len(info["sha256_codigo_activo_16"]) == 16


def test_stale_module_is_reloaded_before_reading_documents():
    def old_reader(imagen):
        return [{"trabajador_rut": "123", "dias_trabajados_fonasa": 2}]

    def old_cell(imagen, x0, x1, y0, y1):
        return 2

    stale = SimpleNamespace(
        __file__=str(
            Path(runtime.__file__).with_name("fonasa_nomina_simple.py")
        ),
        _nomina_de_imagen=old_reader,
        _dias_celda=old_cell,
    )
    with patch.object(
        runtime.importlib, "import_module", return_value=stale
    ), patch.object(
        runtime.importlib, "reload", return_value=original
    ) as reload_mock:
        selected = runtime.cargar_lector_fonasa()
    assert selected is original
    reload_mock.assert_called_once_with(stale)


def test_five_untraceable_workers_are_rejected_not_shown_as_valid():
    old_workers = [
        {
            "trabajador_rut": f"rut{i}",
            "dias_trabajados_fonasa": dias,
        }
        for i, dias in enumerate([24, 2, None, 27, 13])
    ]
    legacy = [{"pagina": 4, "trabajadores": old_workers}]
    recovered = [
        {
            "pagina": 4,
            "trabajadores": [
                {
                    "trabajador_rut": f"rut{i}",
                    "dias_trabajados_fonasa": dias,
                    "traza_dias": [{
                        "valor": dias, "metodo": "ocr_numero"
                    }],
                }
                for i, dias in enumerate([24, 11, 27, 27, 13])
            ],
        }
    ]
    function = Mock(side_effect=[legacy, recovered])
    fake_mod = SimpleNamespace(
        _nomina_de_imagen=original._nomina_de_imagen,
        _dias_celda=original._dias_celda,
        extraer_nomina_fonasa=function,
    )
    with patch.object(
        runtime, "cargar_lector_fonasa", return_value=fake_mod
    ), patch.object(
        runtime.importlib, "reload", return_value=fake_mod
    ):
        result = runtime.extraer_fonasa_con_contrato(
            b"synthetic", paginas_candidatas=[3],
        )
    assert function.call_count == 2
    assert [
        w["dias_trabajados_fonasa"]
        for w in result[0]["trabajadores"]
    ] == [24, 11, 27, 27, 13]


def test_missing_trace_twice_is_not_silenced():
    old = [{"pagina": 4, "trabajadores": [
        {"trabajador_rut": "demo", "dias_trabajados_fonasa": 2}
    ]}]
    fake_mod = SimpleNamespace(
        _nomina_de_imagen=original._nomina_de_imagen,
        _dias_celda=original._dias_celda,
        extraer_nomina_fonasa=Mock(return_value=old),
    )
    with patch.object(
        runtime, "cargar_lector_fonasa", return_value=fake_mod
    ), patch.object(
        runtime.importlib, "reload", return_value=fake_mod
    ):
        try:
            runtime.extraer_fonasa_con_contrato(
                b"synthetic", paginas_candidatas=[3],
            )
        except RuntimeError as exc:
            assert "no hay traza" in str(exc).lower()
        else:
            raise AssertionError("An untraceable 2 was silently accepted")


def test_no_workers_is_not_fabricated_as_ocr_failure():
    assert runtime._nomina_tiene_traza([]) is True
    assert runtime._nomina_tiene_traza([
        {"pagina": 4, "trabajadores": []}
    ]) is True


def _falsa_nomina_digital():
    return [{
        "pagina": 1, "institucion_salud": "Fonasa",
        "trabajadores": [{
            "trabajador_rut": "RUT_FICTICIO_A",
            "trabajador_nombre": "PRUEBA A",
            "dias_trabajados_fonasa": 24,
            "traza_dias": [{"valor": 24, "metodo": "texto_pdf_fonasa"}],
        }],
    }]


def _falsa_nomina_ocr():
    return [{
        "pagina": 2, "institucion_salud": "Fonasa",
        "trabajadores": [{
            "trabajador_rut": "RUT_FICTICIO_B",
            "trabajador_nombre": "PRUEBA B",
            "dias_trabajados_fonasa": 19,
            "traza_dias": [{"valor": 19, "metodo": "ocr_numero"}],
        }],
    }]


def test_pdf_hibrido_agrega_ocr_y_no_pierde_nativo():
    from planillas_texto_digital import extraer_nominas_pdf_texto
    lectura = Mock(return_value=_falsa_nomina_ocr())
    lector = SimpleNamespace(extraer_nomina_fonasa=lectura)
    diagnostico = {}
    with patch(
        "planillas_texto_digital.extraer_nominas_pdf_texto",
        return_value=_falsa_nomina_digital(),
    ), patch.object(
        runtime, "_paginas_raster", return_value=([2], 0, [])
    ), patch.object(
        runtime, "cargar_lector_fonasa", return_value=lector
    ):
        result = runtime.extraer_fonasa_con_contrato(
            b"PDF-FICTICIO", diagnostico=diagnostico
        )
    assert len(result) == 2
    assert [x["pagina"] for x in result] == [1, 2]
    assert diagnostico["cobertura_parcial"] is False
    assert diagnostico["paginas_ocr_intentadas"] == [2]
    lectura.assert_called_once()


def test_pdf_hibrido_sin_nuevas_nóminas_alerta_en_vez_de_omitir():
    diagnostico = {}
    lector = SimpleNamespace(extraer_nomina_fonasa=Mock(return_value=[]))
    with patch(
        "planillas_texto_digital.extraer_nominas_pdf_texto",
        return_value=_falsa_nomina_digital(),
    ), patch.object(
        runtime, "_paginas_raster", return_value=([2], 0, [])
    ), patch.object(
        runtime, "cargar_lector_fonasa", return_value=lector
    ):
        result = runtime.extraer_fonasa_con_contrato(
            b"PDF-FICTICIO", diagnostico=diagnostico
        )
    assert len(result) == 1
    assert diagnostico["cobertura_parcial"] is True
    assert diagnostico["paginas_pendientes"] == [2]


def test_pdf_hibrido_ocr_sin_traza_no_acepta_dias():
    lectura = _falsa_nomina_ocr()
    del lectura[0]["trabajadores"][0]["traza_dias"]
    diagnostico = {}
    lector = SimpleNamespace(extraer_nomina_fonasa=Mock(return_value=lectura))
    with patch(
        "planillas_texto_digital.extraer_nominas_pdf_texto",
        return_value=_falsa_nomina_digital(),
    ), patch.object(
        runtime, "_paginas_raster", return_value=([2], 0, [])
    ), patch.object(
        runtime, "cargar_lector_fonasa", return_value=lector
    ):
        result = runtime.extraer_fonasa_con_contrato(
            b"PDF-FICTICIO", diagnostico=diagnostico
        )
    assert len(result) == 1
    assert diagnostico["cobertura_parcial"] is True
    assert "sin traza" in diagnostico["error_ocr_hibrido"].lower()


def test_pdf_hibrido_presupuesto_y_paginas_pendientes():
    diagnostico = {}
    lector = SimpleNamespace(extraer_nomina_fonasa=Mock(return_value=[]))
    with patch(
        "planillas_texto_digital.extraer_nominas_pdf_texto",
        return_value=_falsa_nomina_digital(),
    ), patch.object(
        runtime, "_paginas_raster",
        return_value=(list(range(2, 14)), 1, []),
    ), patch.object(
        runtime, "cargar_lector_fonasa", return_value=lector
    ):
        runtime.extraer_fonasa_con_contrato(
            b"PDF-FICTICIO", diagnostico=diagnostico
        )
    assert len(diagnostico["paginas_ocr_intentadas"]) == 8
    assert diagnostico["paginas_sin_inspeccionar"] == 1
    assert 13 in diagnostico["paginas_pendientes"]
    assert diagnostico["cobertura_parcial"]


def test_detector_raster_distingue_logo_de_pagina_escaneada():
    import fitz
    with fitz.open() as pdf:
        img = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, 4, 4), False)
        img.clear_with(255)
        pagina = pdf.new_page(width=300, height=200)
        pagina.insert_text((20, 30), "PAGINA DIGITAL")
        pagina.insert_image(fitz.Rect(10, 10, 30, 30), pixmap=img)
        pagina = pdf.new_page(width=300, height=200)
        pagina.insert_image(pagina.rect, pixmap=img)
        contenido = pdf.tobytes()
    paginas, excedentes, inciertas = runtime._paginas_raster(contenido)
    assert paginas == [2]
    assert excedentes == 0
    assert inciertas == []


def test_pdf_hibrido_contradiccion_en_mismos_dias_bloquea_resultado():
    original = _falsa_nomina_digital()
    contradictorio = _falsa_nomina_ocr()
    contradictorio[0]["pagina"] = 1
    contradictorio[0]["trabajadores"][0]["trabajador_rut"] = "RUT_FICTICIO_A"
    diagnostico = {}
    lector = SimpleNamespace(
        extraer_nomina_fonasa=Mock(return_value=contradictorio)
    )
    with patch(
        "planillas_texto_digital.extraer_nominas_pdf_texto",
        return_value=original,
    ), patch.object(
        runtime, "_paginas_raster", return_value=([1], 0, [])
    ), patch.object(
        runtime, "cargar_lector_fonasa", return_value=lector
    ):
        resultado = runtime.extraer_fonasa_con_contrato(
            b"PDF-FICTICIO", diagnostico=diagnostico
        )
    persona = resultado[0]["trabajadores"][0]
    assert persona["dias_trabajados_fonasa"] is None
    assert persona["dias_requieren_revision"] is True
    assert diagnostico["conflictos_ocr"] == 1
    assert diagnostico["cobertura_parcial"]


def test_pdf_hibrido_caida_ocr_no_borra_nomina_digital():
    lector = SimpleNamespace(
        extraer_nomina_fonasa=Mock(
            side_effect=RuntimeError("motor no disponible")
        )
    )
    diagnostico = {}
    with patch(
        "planillas_texto_digital.extraer_nominas_pdf_texto",
        return_value=_falsa_nomina_digital(),
    ), patch.object(
        runtime, "_paginas_raster", return_value=([2], 0, [])
    ), patch.object(
        runtime, "cargar_lector_fonasa", return_value=lector
    ):
        resultado = runtime.extraer_fonasa_con_contrato(
            b"PDF-FICTICIO", diagnostico=diagnostico
        )
    assert len(resultado) == 1
    assert resultado[0]["trabajadores"][0]["dias_trabajados_fonasa"] == 24
    assert diagnostico["paginas_pendientes"] == [2]
    assert diagnostico["cobertura_parcial"]
    assert "motor no disponible" in diagnostico["error_ocr_hibrido"]
