"""Verificación interna de coherencia antes de mostrar días Fonasa.

No certifica el valor contra el PDF; distingue dato rastreable de cifra
producida por el OCR. Ante incoherencia se bloquea la cifra.
"""
from __future__ import annotations


def comprobar_traza_dias(registro: dict) -> dict:
    traza = registro.get("traza_dias", []) or []
    valor = registro.get("dias_trabajados_fonasa")
    positivos = [
        paso.get("valor") for paso in traza
        if isinstance(paso.get("valor"), int)
        and not isinstance(paso.get("valor"), bool)
        and 1 <= paso["valor"] <= 31
    ]
    if not traza:
        return {
            "estado": "SIN_TRAZA",
            "valor_confiable": None,
            "observacion": "El servidor no entregó diagnóstico de OCR por fila.",
        }
    if valor is None:
        return {
            "estado": "REVISAR_DOCUMENTO",
            "valor_confiable": None,
            "observacion": (
                "Ningún día positivo inequívoco o varios movimientos positivos."
            ),
        }
    if len(positivos) != 1 or positivos[0] != valor:
        return {
            "estado": "CONTRADICCION_INTERNA",
            "valor_confiable": None,
            "observacion": (
                "El día mostrado no coincide con una única celda de la traza."
            ),
        }
    metodo = next(
        (p.get("metodo") for p in traza if p.get("valor") == valor),
        "",
    )
    if metodo == "dos_trazos_geometricos":
        estado = "GEOMETRIA_OCR"
        nota = "Detectado por forma de dos trazos; validar visualmente."
    elif metodo == "ocr_numero":
        estado = "LECTURA_OCR"
        nota = "Leído por Tesseract, pendiente de cotejo con PDF."
    elif metodo == "ocr_rapidocr":
        estado = "OCR_ALTERNATIVO_REVISAR"
        nota = (
            "Días propuestos por RapidOCR tras fallar Tesseract; "
            "cotejar con la celda del PDF antes de aprobar el pago."
        )
    else:
        estado = "SIN_METODO"
        nota = "Falta identificar la regla que produjo la lectura."
        valor = None
    return {
        "estado": estado,
        "valor_confiable": valor,
        "observacion": nota,
    }
