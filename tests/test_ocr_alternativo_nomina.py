"""Segunda IA para días: nunca procesar todas las celdas salvo fallo real."""
from types import SimpleNamespace
from unittest.mock import patch

from PIL import Image

from ocr_alternativo_nomina import leer_columna_dias_rapidocr
from fonasa_nomina_simple import _nomina_de_imagen
from fonasa_validacion import comprobar_traza_dias


def test_rapidocr_local_mapea_solo_digitos_con_confianza_alta():
    image = Image.new("L", (120, 80), 255)
    fake = SimpleNamespace(
        txts=["11", "27", "2"],
        scores=[.99, .96, .12],
        boxes=[
            [(4, 8), (42, 8), (42, 12), (4, 12)],
            [(4, 48), (42, 48), (42, 52), (4, 52)],
            [(4, 65), (42, 65), (42, 69), (4, 69)]
        ],
    )
    with patch("rapidocr_pago._motor", return_value=lambda a: fake):
        resultados = leer_columna_dias_rapidocr(
            image, [0, 20, 40], 8, 82
        )
    assert resultados[0][0] == 11
    assert resultados[1][0] == 27
    assert len(resultados) == 2


def _reproducir_tabla(dias, alternativas):
    filas = [100, 126, 152]
    cols = [5, 22, 65, 110, 155, 220, 260]
    respuestas = [
        {0: "21.539.151-5", 1: "21.539.151-5"},
        {0: "BAEZA", 1: "BAEZA"},
        {0: "MANRIQUEZ", 1: "MANRIQUEZ"},
        {0: "MANUEL ALFONSO", 1: "MANUEL ALFONSO"},
    ]
    with patch(
        "fonasa_nomina_simple._reticula", return_value=(filas, cols)
    ), patch(
        "fonasa_nomina_simple._ocr_columna", side_effect=respuestas
    ), patch(
        "fonasa_nomina_simple._dias_celda", side_effect=dias
    ), patch(
        "fonasa_nomina_simple._grafia_celda_dias",
        return_value=(False, False)
    ), patch(
        "ocr_alternativo_nomina.leer_columna_dias_rapidocr",
        return_value=alternativas
    ) as alt:
        filas = _nomina_de_imagen(
            Image.new("L", (300, 300), 255),
            usar_ocr_alternativo=True,
        )
    return filas, alt.call_count


def test_rescate_un_dia_por_persona_no_suma_movimientos():
    filas, veces = _reproducir_tabla([None, None], {0: (11, .99)})
    assert veces == 1
    assert filas[0]["dias_trabajados_fonasa"] == 11
    assert filas[0]["traza_dias"][0]["metodo"] == "ocr_rapidocr"
    assert comprobar_traza_dias(filas[0])["estado"] == "OCR_ALTERNATIVO_REVISAR"


def test_ocr_primario_ya_resuelto_no_llama_segunda_ia():
    filas, veces = _reproducir_tabla([24, None], {0: (27, .99)})
    assert filas[0]["dias_trabajados_fonasa"] == 24
    assert veces == 0


def test_dos_dias_incompatibles_no_se_reemplazan_por_ia():
    filas, veces = _reproducir_tabla(
        [24, 27], {0: (27, .99)}
    )
    assert filas[0]["dias_trabajados_fonasa"] is None
    assert veces == 0


def test_segunda_ia_de_baja_confianza_no_inventa_dias():
    image = Image.new("L", (120, 80), 255)
    fake = SimpleNamespace(
        txts=["2"], scores=[.30],
        boxes=[[(5, 10), (45, 10), (45, 15), (5, 15)]],
    )
    with patch("rapidocr_pago._motor", return_value=lambda a: fake):
        assert leer_columna_dias_rapidocr(
            image, [0, 20, 40], 8, 82
        ) == {}
