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
