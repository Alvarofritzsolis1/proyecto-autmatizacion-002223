"""OCR real del motor Tesseract sobre cifras SINTÉTICAS, no PDF privados.

120 casos verifican que el guard nunca acepte un valor distinto al impreso.
Otros controles deliberados prueban las confusiones 27->2 y 13->3.
Estos tests NO reemplazan un benchmark privado de pagos de cotizaciones.
"""
from __future__ import annotations
import io
import pytest
from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageFont

from fonasa_nomina_simple import _dias_celda
from ocr_control_estricto import evaluar_cifra


def _celda(numero):
    img=Image.new("L", (84, 30), 255)
    d=ImageDraw.Draw(img)
    d.rectangle((0, 0, 83, 29), outline=0, width=2)
    font=ImageFont.truetype(
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 17
    )
    txt=str(numero)
    b=d.textbbox((0,0), txt, font=font)
    d.text(
        ((84-(b[2]-b[0]))/2, (30-(b[3]-b[1]))/2-b[1]),
        txt, font=font, fill=0
    )
    return img


def _variante(img, transform):
    if transform=="original": return img
    if transform=="brillo_0.9":
        return ImageEnhance.Brightness(img).enhance(.9)
    if transform=="blur_0.5":
        return img.filter(ImageFilter.GaussianBlur(.5))
    if transform=="jpeg_80":
        buf=io.BytesIO()
        img.save(buf, format="JPEG", quality=80)
        buf.seek(0)
        return Image.open(buf).convert("L")
    raise ValueError(transform)


@pytest.mark.parametrize("numero",range(1,31))
@pytest.mark.parametrize("variante",["original","brillo_0.9","blur_0.5","jpeg_80"])
def test_120_lecturas_ocr_no_aprueban_dias_falsos(
    monkeypatch, numero, variante
):
    monkeypatch.setenv("GALANT_OCR_STRICT_MODE", "1")
    img=_variante(_celda(numero),variante)
    resultado=_dias_celda(img,0,83,0,29,diagnostico={})
    # CERO valores falsos ACEPTADOS: la abstención es válida.
    assert resultado is None or resultado == numero, (
        f"Falso día aprobado: real={numero}, resultado={resultado}, "
        f"variante={variante}"
    )


@pytest.mark.parametrize(
    "real,numero_falso",
    [(27,2),(13,3),(24,2),(30,3),(27,11),(13,1)]
)
def test_la_guardia_no_confunde_digitos_con_cantidad_equivocada(
    real, numero_falso
):
    resultado, motivo=evaluar_cifra(_celda(real),numero_falso)
    assert resultado is None, (real,numero_falso,motivo)


def test_cero_o_nulo_no_significa_impago():
    assert evaluar_cifra(_celda(0),0)[0] is None
    assert evaluar_cifra(_celda(0),None)[0] is None


def test_no_aprueba_dias_fuera_del_rango():
    assert evaluar_cifra(_celda(1),32)[0] is None
    assert evaluar_cifra(_celda(1),-1)[0] is None


def test_fallo_del_control_es_abstencion_no_aceptacion(monkeypatch):
    monkeypatch.setenv("GALANT_OCR_STRICT_MODE", "1")
    monkeypatch.setattr(
        "ocr_control_estricto.evaluar_recorte",
        lambda *args: (_ for _ in ()).throw(ValueError("error al analizar"))
    )
    diag={}
    assert _dias_celda(_celda(24),0,83,0,29,diagnostico=diag) is None
    assert diag["estado_control_estricto"] == "FALLO_CONTROL_ESTRICTO"
