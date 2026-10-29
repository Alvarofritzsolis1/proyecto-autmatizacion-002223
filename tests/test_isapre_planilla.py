"""La planilla Isapre no contiene por defecto columna de días trabajados."""
from unittest.mock import patch
from PIL import Image
import fitz

from fonasa_nomina_simple import (
    _tipo_salud, _nomina_de_imagen_isapre, extraer_nomina_fonasa
)
from pago_documental import _institucion


def test_encabezado_identifica_fonasa():
    assert _tipo_salud("FONASA PLANILLA DETALLE COTIZACIONES DE SALUD") == "Fonasa"


def test_encabezado_identifica_isapre_con_nombre():
    assert _tipo_salud(
        "PLANILLA DE DECLARACION Y PAGO DE COTIZACIONES "
        "DE SALUD A ISAPRES - CONSALUD - DETALLE"
    ) == "Isapre Consalud"
    assert _tipo_salud(
        "PLANILLA DETALLE COTIZACIONES DE SALUD ISAPRE CRUZBLANCA"
    ) == "Isapre Cruz Blanca"


def test_no_llamar_isapre_a_una_planilla_afp():
    assert _tipo_salud("AFP MODELO DETALLE DE COTIZACIONES") == ""


def test_isapre_no_utiliza_columna_de_remuneracion_como_dias():
    filas = [100, 134, 168]
    cols = [5, 21, 77, 111, 205, 235, 267, 298]
    respuestas = [
        {0: "12.345.678-5", 1: "12.345.678-5"},  # RUT
        {0: "PEREZ GOMEZ ANA", 1: "PEREZ GOMEZ ANA"},  # NOMBRE
        {0: "2500000", 1: "2500000"},  # RENTA: nunca interpretarla como días
    ]
    with patch(
        "fonasa_nomina_simple._reticula", return_value=(filas, cols)
    ), patch(
        "fonasa_nomina_simple._ocr_columna", side_effect=respuestas
    ):
        registros = _nomina_de_imagen_isapre(
            Image.new("L", (300, 300), 255)
        )
    assert len(registros) == 1
    assert registros[0]["trabajador_rut"] == "12.345.678-5"
    assert registros[0]["trabajador_nombre"].startswith("PEREZ GOMEZ ANA")
    assert registros[0]["dias_trabajados_fonasa"] is None
    assert registros[0]["traza_dias"][0]["metodo"] == "dias_no_informados_en_planilla_isapre"


def test_anexo_siguiente_isapre_sin_titulo_se_puede_leer():
    doc = fitz.open()
    for _ in range(2):
        doc.new_page(width=612, height=792)
    pdf = doc.tobytes()
    doc.close()
    ejemplo = [{
        "trabajador_rut": "12.345.678-5",
        "trabajador_nombre": "PEREZ GOMEZ ANA",
        "dias_trabajados_fonasa": None,
        "traza_dias": [{"valor": None,"metodo":"dias_no_informados_en_planilla_isapre"}],
    }]
    with patch("fonasa_nomina_simple._es_anexo_fonasa", return_value=""), \
         patch("fonasa_nomina_simple._nomina_de_imagen_isapre",
               return_value=ejemplo):
        out = extraer_nomina_fonasa(
            pdf, paginas_candidatas=[1],
            instituciones_candidatas={1:"Isapre Consalud"},
        )
    assert len(out)==1
    assert out[0]["pagina"]==2
    assert out[0]["institucion_salud"]=="Isapre Consalud"
    assert out[0]["trabajadores"][0]["sistema_salud"]=="Isapre"


def test_recibos_previred_reconocen_isapres():
    assert _institucion("ISAPRE COLMENA PLANILLA DE PAGO") == "Isapre Colmena"
    assert _institucion("ISAPRE CRUZBLANCA PAGO") == "Isapre Cruz Blanca"
    assert _institucion("FONASA PAGO ELECTRONICO") == "Fonasa"
