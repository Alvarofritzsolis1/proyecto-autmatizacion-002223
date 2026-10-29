"""Rescate rápido de anexos en PDF escaneados usando SOLO geometría de tablas.

No extrae ni transmite datos personales: localiza páginas candidatas para
enviar al lector ya existente. No presupone que un recibo exista o sea legible.
"""
from __future__ import annotations
import fitz
import cv2
import numpy as np


def _centros(valores, salto=2):
    grupos = []
    for v in valores:
        n = int(v)
        if grupos and n - grupos[-1][-1] <= salto:
            grupos[-1].append(n)
        else:
            grupos.append([n])
    return [int(round(np.median(g))) for g in grupos]


def _score_tabla(imagen):
    """Cantidad de filas y columnas en una cuadrícula sin OCR."""
    h, w = imagen.shape[:2]
    _, neg = cv2.threshold(
        imagen, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU
    )
    horizontal = cv2.morphologyEx(
        neg, cv2.MORPH_OPEN,
        cv2.getStructuringElement(
            cv2.MORPH_RECT, (max(50, int(w * .10)), 1)
        )
    )
    cuenta = np.count_nonzero(horizontal, axis=1)
    ys = _centros(np.flatnonzero(
        (cuenta > w * .22)
        & (np.arange(h) > h * .16)
        & (np.arange(h) < h * .78)
    ))
    cadena_max = []
    for i in range(len(ys)):
        cadena = [ys[i]]
        for y in ys[i + 1:]:
            if 5 <= y - cadena[-1] <= 23:
                cadena.append(y)
            else:
                break
        if len(cadena) > len(cadena_max):
            cadena_max = cadena
    if len(cadena_max) < 8:
        return 0, 0
    alto = cadena_max[-1] - cadena_max[0]
    vertical = cv2.morphologyEx(
        neg[cadena_max[0]:cadena_max[-1]], cv2.MORPH_OPEN,
        cv2.getStructuringElement(
            cv2.MORPH_RECT, (1, max(12, int(alto * .13)))
        )
    )
    xs = _centros(np.flatnonzero(
        np.count_nonzero(vertical, axis=0) > alto * .50
    ))
    return len(cadena_max), len(xs)


def buscar_paginas_con_planilla(contenido: bytes, *, max_paginas=24):
    """Páginas 1-based de posibles planillas, NO confirmación de salud/pago."""
    candidatas = []
    with fitz.open(stream=contenido, filetype="pdf") as doc:
        for indice in range(min(len(doc), max_paginas)):
            pagina = doc[indice]
            pix = pagina.get_pixmap(
                matrix=fitz.Matrix(1.4, 1.4),
                colorspace=fitz.csGRAY, alpha=False,
            )
            arr = np.frombuffer(
                pix.samples, dtype=np.uint8
            ).reshape(pix.height, pix.width)
            if pix.height > pix.width:
                arr = cv2.rotate(arr, cv2.ROTATE_90_COUNTERCLOCKWISE)
            filas, cols = _score_tabla(arr)
            if filas >= 11 and cols >= 7:
                candidatas.append({
                    "pagina": indice + 1,
                    "filas": filas,
                    "columnas": cols,
                })
    return sorted(
        candidatas,
        key=lambda x: (-x["filas"], -x["columnas"], x["pagina"])
    )
