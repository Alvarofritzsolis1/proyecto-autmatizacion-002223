"""Protege GALANT contra versiones antiguas del lector Fonasa en memoria.

Streamlit puede re-ejecutar app.py mientras un módulo importado continúa en
sys.modules. Un hash del archivo en disco NO prueba qué bytecode ejecuta OCR.
No se hace OCR adicional excepto si el resultado incumple el contrato.
"""
from __future__ import annotations

import hashlib
import importlib
import inspect
import marshal
import time
from pathlib import Path
from typing import Any

NOMBRE_MODULO = "fonasa_nomina_simple"


def _contrato_valido(modulo: Any) -> bool:
    """El bytecode activo debe producir traza, no basta un archivo actualizado."""
    lector = getattr(modulo, "_nomina_de_imagen", None)
    celda = getattr(modulo, "_dias_celda", None)
    if lector is None or celda is None:
        return False
    if "diagnostico" not in inspect.signature(celda).parameters:
        return False
    # CPython suele guardar las claves de un dict en una tupla de constantes
    # de BUILD_CONST_KEY_MAP; comparar solo cadenas sueltas daría falso.
    constantes = lector.__code__.co_consts
    return any(
        constante == "traza_dias"
        or (
            isinstance(constante, (tuple, list))
            and "traza_dias" in constante
        )
        for constante in constantes
    )


def cargar_lector_fonasa():
    modulo = importlib.import_module(NOMBRE_MODULO)
    archivo_esperado = Path(__file__).with_name(NOMBRE_MODULO + ".py").resolve()
    archivo_cargado = Path(getattr(modulo, "__file__", "")).resolve()
    if archivo_cargado != archivo_esperado:
        raise RuntimeError(
            "Fonasa: Python importó el módulo desde otra ubicación; "
            "reinicia la aplicación y verifica las dependencias."
        )
    if not _contrato_valido(modulo):
        # Recargar solo cuando detectamos bytecode viejo: no hacerlo en cada PDF.
        importlib.invalidate_caches()
        modulo = importlib.reload(modulo)
    if not _contrato_valido(modulo):
        raise RuntimeError(
            "Fonasa: el código cargado no contiene traza por celda "
            "aunque el archivo en disco esté actualizado. Reiniciar servidor."
        )
    return modulo


def estado_lector_fonasa() -> dict:
    modulo = cargar_lector_fonasa()
    archivo = Path(modulo.__file__)
    codigo = modulo._nomina_de_imagen.__code__
    return {
        "archivo": archivo.name,
        "sha256_fuente_16": hashlib.sha256(archivo.read_bytes()).hexdigest()[:16],
        "sha256_codigo_activo_16": hashlib.sha256(marshal.dumps(codigo)).hexdigest()[:16],
        "contrato_traza": _contrato_valido(modulo),
    }


def _nomina_tiene_traza(nomina: list) -> bool:
    return all(
        isinstance(fila.get("traza_dias"), list)
        and bool(fila["traza_dias"])
        for anexo in nomina for fila in anexo.get("trabajadores", [])
    )


def extraer_fonasa_con_contrato(contenido: bytes, *, paginas_candidatas=None,
                                instituciones_candidatas=None,
                                diagnostico=None, usar_ocr_alternativo=False):
    """OCR primero en páginas conocidas; rescate geométrico solo si falla.

    La etapa rápida no requiere identificar un recibo. Si el OCR produce
    personas sin traza, se rechaza antes de devolver valores inventados.
    """
    inicio = time.perf_counter()
    modulo = cargar_lector_fonasa()
    nomina = modulo.extraer_nomina_fonasa(
        contenido, paginas_candidatas=paginas_candidatas,
        instituciones_candidatas=instituciones_candidatas,
    )
    modo = "paginas_por_comprobante"
    candidatas = []
    if not nomina:
        # ERROR ANTERIOR: un recibo ilegible dejaba nomina=[] sin intentar
        # localizar el ANEXO por su retícula (aunque la página 4 fuera clara).
        from rescate_planillas import buscar_paginas_con_planilla
        candidatas = buscar_paginas_con_planilla(
            contenido, max_paginas=24
        )
        paginas_rescate = [
            max(1, p["pagina"] - 1) for p in candidatas[:8]
        ]
        if paginas_rescate:
            modo = "rescate_por_reticula"
            nomina = modulo.extraer_nomina_fonasa(
                contenido, paginas_candidatas=paginas_rescate,
                instituciones_candidatas=instituciones_candidatas,
            )
    if not nomina and candidatas and usar_ocr_alternativo:
        # SOLO cuando la retícula encontró tablas y Tesseract no identificó
        # una planilla de salud, pedir a RapidOCR una segunda lectura del
        # encabezado. RapidOCR NO inventa nombres/días: solo da una pista
        # para repetir el lector estructurado.
        from rescate_planillas import rescatar_institucion_rapidocr
        sugerencias = rescatar_institucion_rapidocr(
            contenido, (x["pagina"] for x in candidatas[:3])
        )
        if sugerencias:
            modo = "rapidocr_encabezado_mas_lector_tabla"
            pistas = dict(instituciones_candidatas or {})
            pistas.update(sugerencias)
            nomina = modulo.extraer_nomina_fonasa(
                contenido,
                paginas_candidatas=[
                    max(1, x["pagina"] - 1) for x in candidatas[:3]
                ],
                instituciones_candidatas=pistas,
            )
    if nomina and not _nomina_tiene_traza(nomina):
        importlib.invalidate_caches()
        modulo = importlib.reload(modulo)
        if not _contrato_valido(modulo):
            raise RuntimeError("Salud: bytecode OCR desactualizado tras recarga.")
        nomina = modulo.extraer_nomina_fonasa(
            contenido, paginas_candidatas=paginas_candidatas,
            instituciones_candidatas=instituciones_candidatas,
        )
        if not _nomina_tiene_traza(nomina):
            raise RuntimeError(
                "Salud: no hay traza de días por trabajador después "
                "de repetir el OCR; no mostrar días sin procedencia."
            )
    if diagnostico is not None:
        diagnostico.update({
            "ruta": modo,
            "paginas_rescate": [x["pagina"] for x in candidatas],
            "duracion_segundos": round(time.perf_counter() - inicio, 3),
            "segundo_motor_habilitado": bool(usar_ocr_alternativo),
            "trabajadores_encontrados": sum(
                len(x.get("trabajadores", [])) for x in nomina
            ),
        })
    return nomina
