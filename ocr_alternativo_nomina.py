"""Segunda IA OCR de código abierto para días DUDOSOS de planillas Fonasa.

No se ejecuta si el primer lector ya recuperó días. Una inferencia por
columna de días como máximo (no un proceso por trabajador). No sube datos a
internet y jamás toma cotización o remuneración como días.
"""
from __future__ import annotations
import re
import numpy as np
from PIL import Image


def leer_columna_dias_rapidocr(imagen, filas, x0, x1, *, confianza_min=.94):
    """Devuelve {índice_fila: (días, confianza)} solo para lecturas inequívocas."""
    try:
        from rapidocr_pago import _motor, _LOCK
    except ImportError:
        return {}
    if len(filas) < 2 or x1-x0 < 14:
        return {}
    recorte = imagen.convert("RGB").crop((
        x0+7, filas[0]+1, x1-5, filas[-1]-1
    ))
    escala = 2
    recorte = recorte.resize(
        (recorte.width*escala, recorte.height*escala),
        Image.Resampling.BICUBIC
    )
    try:
        with _LOCK:
            resultado = _motor()(np.asarray(recorte))
    except (ImportError, OSError, ValueError, RuntimeError, TypeError):
        return {}
    cajas = getattr(resultado, "boxes", None)
    textos = getattr(resultado, "txts", None)
    scores = getattr(resultado, "scores", None)
    if cajas is None or textos is None or scores is None:
        return {}
    candidatos = {}
    for caja, texto, score in zip(cajas, textos, scores):
        texto = re.sub(r"\s", "", str(texto))
        if (not re.fullmatch(r"0?[1-9]|[12][0-9]|3[01]", texto)
                or float(score) < confianza_min):
            continue
        puntos = np.asarray(caja)
        centro = float(puntos[:, 1].mean())/escala + filas[0]+1
        for i in range(len(filas)-1):
            if filas[i] <= centro < filas[i+1]:
                candidatos.setdefault(i, []).append(
                    (int(texto), round(float(score), 3))
                )
                break
    # Si hay dos lecturas distintas para la misma celda, no elegir una.
    resultado_seguro = {}
    for i, opciones in candidatos.items():
        valores = {v for v, _ in opciones}
        if len(valores) == 1:
            resultado_seguro[i] = max(opciones, key=lambda x: x[1])
    return resultado_seguro
