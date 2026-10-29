"""Tests sintéticos sin documentos personales reales."""
import fitz
from PIL import Image
from unittest.mock import patch

from fonasa_nomina_simple import (
    normalizar_rut, _nomina_de_imagen, extraer_nomina_fonasa
)


def test_rut_trabajador_con_digito_valido():
    assert normalizar_rut("21.539.151-5") == "21.539.151-5"
    assert normalizar_rut("17.898.006-8") == "17.898.006-8"
    assert normalizar_rut("17.898.006-9") == ""


def test_movimientos_no_generan_trabajadores_duplicados():
    # Imagen sintética: el primero tiene 2 movimientos y el segundo 2.
    filas = [100, 126, 152, 178, 204]
    cols = [5, 22, 65, 110, 155, 220, 260]
    respuestas = [
        {0:"11.111.111-1",1:"11.111.111-1",2:"12.345.678-5",3:"12.345.678-5"},
        {0:"ALVAREZ",1:"ALVAREZ",2:"PEREZ",3:"PEREZ"},
        {0:"ROJAS",1:"ROJAS",2:"SOTO",3:"SOTO"},
        {0:"ANA MARIA",1:"ANA MARIA",2:"LUIS MIGUEL",3:"LUIS MIGUEL"},
    ]
    # Solo RUTs reales válidos de prueba, no valores privados.
    # Reemplazar los anclajes por RUTs correctos matemáticamente.
    respuestas[0] = {
        0:"21.539.151-5",1:"21.539.151-5",
        2:"17.898.006-8",3:"17.898.006-8",
    }
    with patch("fonasa_nomina_simple._reticula",return_value=(filas,cols)), \
         patch("fonasa_nomina_simple._ocr_columna",side_effect=respuestas), \
         patch("fonasa_nomina_simple._dias_celda",side_effect=[24,None,11,None]):
        out = _nomina_de_imagen(Image.new("L",(300,300),255))
    assert len(out)==2
    assert out[0]["trabajador_nombre"]=="ANA MARIA ALVAREZ ROJAS"
    assert out[0]["dias_trabajados_fonasa"]==24
    assert out[1]["trabajador_nombre"]=="LUIS MIGUEL PEREZ SOTO"
    assert out[1]["dias_trabajados_fonasa"]==11


def test_dias_ilegibles_no_se_convierten_en_cero_o_impago():
    filas=[100,126,152]
    cols=[5,22,65,110,155,220,260]
    datos=[
        {0:"21.539.151-5",1:"21.539.151-5"},
        {0:"ALVAREZ",1:"ALVAREZ"},
        {0:"ROJAS",1:"ROJAS"},
        {0:"ANA MARIA",1:"ANA MARIA"},
    ]
    with patch("fonasa_nomina_simple._reticula",return_value=(filas,cols)), \
         patch("fonasa_nomina_simple._ocr_columna",side_effect=datos), \
         patch("fonasa_nomina_simple._dias_celda",return_value=None):
        out=_nomina_de_imagen(Image.new("L",(300,300),255))
    assert len(out)==1
    assert out[0]["dias_trabajados_fonasa"] is None
    assert out[0]["dias_requieren_revision"] is True


def test_candidatos_solo_incluyen_recibo_y_anexo_adyacente():
    doc=fitz.open()
    for _ in range(10):doc.new_page()
    contenido=doc.tobytes()
    doc.close()
    cuenta=[]
    def probe(pagina,orientacion):
        cuenta.append((pagina.number,orientacion))
        return pagina.number==3 and orientacion==90
    with patch("fonasa_nomina_simple._es_anexo_fonasa",side_effect=probe), \
         patch("fonasa_nomina_simple._nomina_de_imagen",return_value=[
             {"trabajador_rut":"21.539.151-5","trabajador_nombre":"ANA MARIA ALVAREZ"}
         ]):
        out=extraer_nomina_fonasa(contenido,paginas_candidatas=[3])
    assert out[0]["pagina"]==4
    assert len(out)==1
    assert {i for i,_ in cuenta}<={2,3}


def test_sin_candidatos_no_crea_falsas_nominas():
    doc=fitz.open()
    for _ in range(3):doc.new_page()
    data=doc.tobytes(); doc.close()
    with patch("fonasa_nomina_simple._es_anexo_fonasa",return_value=False):
        assert extraer_nomina_fonasa(data,paginas_candidatas=[1])==[]
