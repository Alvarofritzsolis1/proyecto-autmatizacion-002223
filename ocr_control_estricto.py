"""Guardia conservadora de días de pago para anexos escaneados.

La política no intenta corregir la salida OCR. Solo acepta cifras cuyos
caracteres sean compatibles con la estructura de tinta del recorte original.

Si existe desacuerdo o no puede decidirse, ABSTENER: nunca escribir cero,
inventar días ni inferir falta de pago.

Limitación: una cifra de dos dígitos mal reconocida como otra cifra de dos
dígitos puede pasar. El contrato NO certifica 100% de exactitud.
"""
from __future__ import annotations
import cv2
import numpy as np


def evaluar_cifra(imagen, candidato):
    """(dias_aceptados|None, razon): no modifica el candidato ni el PDF.

    imagen: recorte PIL de una celda, incluido su borde de tabla.
    candidato: valor 1..31 producido por OCR primario o análisis de glifos.
    """
    if (
        candidato is None or isinstance(candidato, bool)
        or not isinstance(candidato, int) or not 1 <= candidato <= 31
    ):
        return None, "OCR_INCIERTO"
    gris = np.asarray(imagen.convert("L"))
    alto, ancho = gris.shape
    if not 16 <= alto <= 400 or not 22 <= ancho <= 1000:
        return None, "CELDA_FUERA_RANGO"
    tinta = cv2.threshold(
        gris, 0, 255,
        cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU
    )[1]
    n, _, stats, _ = cv2.connectedComponentsWithStats(tinta)
    glifos = []
    for x, y, w, h, area in stats[1:]:
        if (
            2 <= w <= round(alto * .40)
            and round(alto * .16) <= h <= round(alto * .65)
            and area >= max(7, int(alto * .28))
            and int(ancho * .12) <= x <= int(ancho * .86)
            and int(alto * .04) <= y <= int(alto * .50)
        ):
            glifos.append((int(x), int(y), int(w), int(h), int(area)))
    glifos.sort(key=lambda x: x[0])
    if len(glifos) != len(str(candidato)):
        return None, "NUMERO_DE_GLIFOS_CONTRADICTORIO"
    if candidato == 11 and any(
        w / h > .50 for _, _, w, h, _ in glifos
    ):
        return None, "ONCE_GEOMETRICAMENTE_NO_CONFIRMADO"
    return candidato, "CONCORDANTE_SOLO_EN_ESTRUCTURA"


def evaluar_recorte(imagen, x0, x1, y0, y1, candidato):
    return evaluar_cifra(imagen.crop((x0, y0, x1, y1)), candidato)
