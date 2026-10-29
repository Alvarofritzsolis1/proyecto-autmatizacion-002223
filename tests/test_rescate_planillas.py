"""Fallos regresivos: un recibo mal leído NO debe ocultar un anexo claro."""
from unittest.mock import Mock, patch
import fitz
import numpy as np
import cv2

import rescate_planillas as rp
import fonasa_runtime as runtime


def test_tabla_morfologica_sin_ocr():
    arr = np.full((650, 1000), 255, dtype=np.uint8)
    for y in range(180, 410, 12):
        cv2.line(arr, (150, y), (850, y), 0, 2)
    for x in range(150, 851, 70):
        cv2.line(arr, (x, 180), (x, 408), 0, 2)
    filas, cols = rp._score_tabla(arr)
    assert filas >= 11
    assert cols >= 7


def test_no_confundir_pagina_sin_tabla_con_anexo():
    arr = np.full((650, 1000), 255, dtype=np.uint8)
    assert rp._score_tabla(arr) == (0, 0)


def _filas_validas():
    return [{
        "pagina": 4,
        "institucion_salud": "Fonasa",
        "trabajadores": [{
            "trabajador_rut": "12.345.678-5",
            "trabajador_nombre": "TRABAJADOR PRUEBA",
            "dias_trabajados_fonasa": 11,
            "traza_dias": [{"fila": 6, "valor": 11,
                             "metodo": "dos_trazos_geometricos"}],
        }]
    }]


def test_si_recibo_no_detecta_personas_rescata_por_geometria():
    fake = Mock()
    fake.extraer_nomina_fonasa.side_effect = [[], _filas_validas()]
    diag = {}
    with patch("fonasa_runtime.cargar_lector_fonasa", return_value=fake), \
         patch("rescate_planillas.buscar_paginas_con_planilla",
               return_value=[{"pagina": 4, "filas": 24, "columnas": 17}]):
        resultado = runtime.extraer_fonasa_con_contrato(
            b"fake", paginas_candidatas=[3], diagnostico=diag
        )
    assert len(resultado) == 1
    assert diag["ruta"] == "rescate_por_reticula"
    assert diag["paginas_rescate"] == [4]
    assert diag["trabajadores_encontrados"] == 1
    assert fake.extraer_nomina_fonasa.call_count == 2
    assert fake.extraer_nomina_fonasa.call_args_list[1].kwargs[
        "paginas_candidatas"
    ] == [3]


def test_no_ejecutar_fallback_cuando_ocr_primario_tiene_traza():
    fake = Mock()
    fake.extraer_nomina_fonasa.return_value = _filas_validas()
    diag = {}
    with patch("fonasa_runtime.cargar_lector_fonasa", return_value=fake), \
         patch("rescate_planillas.buscar_paginas_con_planilla",
               side_effect=AssertionError("scan innecesario")):
        r = runtime.extraer_fonasa_con_contrato(b"fake", diagnostico=diag)
    assert len(r) == 1
    assert fake.extraer_nomina_fonasa.call_count == 1
    assert diag["ruta"] == "paginas_por_comprobante"


def test_rapidocr_como_tercera_opcion_solo_si_primeras_fallan():
    fake = Mock()
    fake.extraer_nomina_fonasa.side_effect = [[], [], _filas_validas()]
    diag = {}
    with patch("fonasa_runtime.cargar_lector_fonasa", return_value=fake), \
         patch("rescate_planillas.buscar_paginas_con_planilla",
               return_value=[{"pagina": 4, "filas": 24, "columnas": 17}]), \
         patch("rescate_planillas.rescatar_institucion_rapidocr",
               return_value={3: "Fonasa"}) as alt:
        r = runtime.extraer_fonasa_con_contrato(
            b"fake", paginas_candidatas=[3], diagnostico=diag,
            usar_ocr_alternativo=True
        )
    assert len(r) == 1
    assert diag["ruta"] == "rapidocr_encabezado_mas_lector_tabla"
    assert fake.extraer_nomina_fonasa.call_count == 3
    assert fake.extraer_nomina_fonasa.call_args_list[-1].kwargs[
        "instituciones_candidatas"
    ][3] == "Fonasa"
    alt.assert_called_once()


def test_no_reintentar_modelo_ia_si_esta_desactivado():
    fake = Mock()
    fake.extraer_nomina_fonasa.side_effect = [[], []]
    with patch("fonasa_runtime.cargar_lector_fonasa", return_value=fake), \
         patch("rescate_planillas.buscar_paginas_con_planilla",
               return_value=[{"pagina": 4, "filas": 20, "columnas": 17}]), \
         patch("rescate_planillas.rescatar_institucion_rapidocr",
               side_effect=AssertionError("Modelo no autorizado")):
        r = runtime.extraer_fonasa_con_contrato(
            b"fake", usar_ocr_alternativo=False
        )
    assert r == []


def test_pdf_digital_sin_tabla_no_fabrica_trabajadores():
    d = fitz.open()
    d.new_page()
    d.new_page()
    data = d.tobytes()
    d.close()
    assert rp.buscar_paginas_con_planilla(data) == []
