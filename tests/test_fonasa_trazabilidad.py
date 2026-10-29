"""Tests verificables de procedencia OCR, sin PDF ni RUT laborales reales."""
from unittest.mock import patch

import pytest
from PIL import Image, ImageDraw, ImageFont

from fonasa_nomina_simple import _dias_celda, _nomina_de_imagen
from fonasa_validacion import comprobar_traza_dias


def _numero_sintetico(valor):
    """Celda de 84x30 con borde y número, lectura real por Tesseract."""
    im = Image.new("L", (84, 30), 255)
    draw = ImageDraw.Draw(im)
    draw.rectangle((0, 0, 83, 29), outline=0, width=2)
    font = ImageFont.truetype(
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 17
    )
    texto = str(valor)
    box = draw.textbbox((0, 0), texto, font=font)
    draw.text(
        ((84-(box[2]-box[0]))/2, (30-(box[3]-box[1]))/2-box[1]),
        texto, font=font, fill=0,
    )
    return im


@pytest.mark.parametrize("valor", [11, 27, 24, 13])
def test_traza_registra_cifra_ocr_real(valor):
    traza = {}
    dias = _dias_celda(
        _numero_sintetico(valor), 0, 83, 0, 29,
        diagnostico=traza,
    )
    assert dias == valor
    assert traza["valor"] == valor
    assert traza["metodo"] in ("ocr_numero", "dos_trazos_geometricos")
    assert traza["celda_px"] == [0, 0, 83, 29]


def test_ocr_falso_dos_sobre_cero_se_bloquea_y_registra():
    traza = {}
    with patch(
        "fonasa_nomina_simple.pytesseract.image_to_string",
        return_value="2",
    ):
        dias = _dias_celda(
            _numero_sintetico(0), 0, 83, 0, 29,
            diagnostico=traza,
        )
    assert dias is None
    assert traza["ocr_bruto"] == "2"
    assert traza["glifo_cerrado"] is True
    assert traza["metodo"] == "rechazado_por_grafia_cerrada"


def test_validador_bloquea_numero_sin_traza():
    r = comprobar_traza_dias({
        "dias_trabajados_fonasa": 27,
        "traza_dias": [],
    })
    assert r["estado"] == "SIN_TRAZA"
    assert r["valor_confiable"] is None


def test_validador_bloquea_dos_positivos():
    r = comprobar_traza_dias({
        "dias_trabajados_fonasa": 27,
        "traza_dias": [
            {"valor": 27, "metodo": "ocr_numero"},
            {"valor": 2, "metodo": "ocr_numero"},
        ],
    })
    assert r["estado"] == "CONTRADICCION_INTERNA"
    assert r["valor_confiable"] is None


def test_validador_bloquea_fecha_extraida_como_dias():
    r = comprobar_traza_dias({
        "dias_trabajados_fonasa": 19,
        "traza_dias": [{"valor": 27, "metodo": "ocr_numero"}],
    })
    assert r["estado"] == "CONTRADICCION_INTERNA"
    assert r["valor_confiable"] is None


def test_validador_no_convierte_cero_en_impago():
    r = comprobar_traza_dias({
        "dias_trabajados_fonasa": None,
        "traza_dias": [
            {"valor": None, "metodo": "movimiento_cero"},
        ],
    })
    assert r["estado"] == "REVISAR_DOCUMENTO"
    assert r["valor_confiable"] is None


def test_validador_identifica_11_por_geometria():
    r = comprobar_traza_dias({
        "dias_trabajados_fonasa": 11,
        "traza_dias": [
            {"valor": 11, "metodo": "dos_trazos_geometricos"},
            {"valor": None, "metodo": "movimiento_cero"},
        ],
    })
    assert r["valor_confiable"] == 11
    assert r["estado"] == "GEOMETRIA_OCR"
    assert "validar visualmente" in r["observacion"]


def test_validador_marca_27_como_ocr_no_certificado():
    r = comprobar_traza_dias({
        "dias_trabajados_fonasa": 27,
        "traza_dias": [
            {"valor": 27, "metodo": "ocr_numero"},
        ],
    })
    assert r["valor_confiable"] == 27
    assert r["estado"] == "LECTURA_OCR"
    assert "pendiente de cotejo" in r["observacion"]


def test_validador_no_confia_en_metodo_desconocido():
    r = comprobar_traza_dias({
        "dias_trabajados_fonasa": 27,
        "traza_dias": [{"valor": 27, "metodo": "no_implementado"}],
    })
    assert r["estado"] == "SIN_METODO"
    assert r["valor_confiable"] is None


def test_nomina_emite_traza_por_movimiento():
    filas = [100, 126, 152]
    columnas = [5, 22, 65, 110, 155, 220, 260]
    columnas_ocr = [
        {0: "12.345.678-5", 1: "12.345.678-5"},
        {0: "PEREZ", 1: "PEREZ"},
        {0: "GOMEZ", 1: "GOMEZ"},
        {0: "CARLOS", 1: "CARLOS"},
    ]
    with patch(
        "fonasa_nomina_simple._reticula", return_value=(filas, columnas)
    ), patch(
        "fonasa_nomina_simple._ocr_columna", side_effect=columnas_ocr
    ), patch(
        "fonasa_nomina_simple._dias_celda", side_effect=[27, None]
    ):
        nomina = _nomina_de_imagen(Image.new("L", (300, 300), 255))
    assert len(nomina) == 1
    r = nomina[0]
    assert r["trabajador_rut"] == "12.345.678-5"
    assert len(r["traza_dias"]) == 2
    assert [x["valor"] for x in r["traza_dias"]] == [27, None]
    assert r["dias_trabajados_fonasa"] == 27
