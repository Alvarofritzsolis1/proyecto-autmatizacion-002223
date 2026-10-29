"""Regresión Fonasa sin datos personales reales.

20 casos numéricos con Tesseract real (incluido 0/no día trabajado).
19 filas artificiales que reproducen un anexo Fonasa con movimientos.
"""
from unittest.mock import patch

import pytest
from PIL import Image, ImageDraw, ImageFont

from fonasa_nomina_simple import _dias_celda, _grafia_celda_dias


def _celda(numero, ancho=84, alto=30):
    imagen = Image.new("L", (ancho, alto), 255)
    dibujo = ImageDraw.Draw(imagen)
    dibujo.rectangle((0, 0, ancho - 1, alto - 1), outline=0, width=2)
    fuente = ImageFont.truetype(
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 17
    )
    texto = str(numero)
    limites = dibujo.textbbox((0, 0), texto, font=fuente)
    dibujo.text(
        (
            (ancho - (limites[2] - limites[0])) / 2,
            (alto - (limites[3] - limites[1])) / 2 - limites[1],
        ),
        texto, font=fuente, fill=0
    )
    return imagen


# 20 valores, varias familias visuales y casos donde una cifra borrosa
# se confundía con una fila de movimiento sin días.
CASOS = [0, 1, 2, 3, 4, 5, 6, 7, 8, 9,
         10, 11, 12, 13, 14, 15, 16, 24, 27, 30]


@pytest.mark.parametrize("numero", CASOS)
def test_veinte_cifras_sin_falsos_dias(numero):
    imagen = _celda(numero)
    esperado = numero if numero > 0 else None
    assert _dias_celda(imagen, 0, 83, 0, 29) == esperado


def test_doble_uno_es_geometrico_y_no_depende_de_ocr():
    imagen = _celda(11)
    assert _grafia_celda_dias(imagen, 0, 83, 0, 29)[0]
    with patch(
        "fonasa_nomina_simple.pytesseract.image_to_string",
        side_effect=AssertionError("No debe consultar OCR en doble 1 claro"),
    ):
        assert _dias_celda(imagen, 0, 83, 0, 29) == 11


def test_falso_dos_sobre_cero_nunca_es_dia_trabajado():
    imagen = _celda(0)
    assert _grafia_celda_dias(imagen, 0, 83, 0, 29)[1]
    with patch(
        "fonasa_nomina_simple.pytesseract.image_to_string",
        return_value="2",
    ):
        assert _dias_celda(imagen, 0, 83, 0, 29) is None


def test_falso_dos_sobre_ocho_no_se_acepta():
    imagen = _celda(8)
    assert _grafia_celda_dias(imagen, 0, 83, 0, 29)[1]
    with patch(
        "fonasa_nomina_simple.pytesseract.image_to_string",
        return_value="2",
    ):
        assert _dias_celda(imagen, 0, 83, 0, 29) is None


def test_19_movimientos_no_duplican_dias():
    datos = [24, 0, 0, 0, 0, 11, 0, 0, 0, 0,
             27, 0, 0, 27, 0, 0, 13, 0, 0]
    obtenidos = [
        _dias_celda(_celda(n), 0, 83, 0, 29)
        for n in datos
    ]
    assert obtenidos == [
        24, None, None, None, None, 11, None, None, None, None,
        27, None, None, 27, None, None, 13, None, None,
    ]
    assert [v for v in obtenidos if v is not None] == [24, 11, 27, 27, 13]


def test_digitos_conflictivos_no_cambian_estado_de_pago():
    imagen = _celda(0)
    assert _dias_celda(imagen, 0, 83, 0, 29) is None
    # El módulo entrega días, pero no tiene ninguna función que marque IMPAGO.
    assert not hasattr(__import__("fonasa_nomina_simple"), "marcar_impago")
