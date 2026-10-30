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
import fitz
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


def _paginas_raster(contenido: bytes, *, limite_inspeccion=80):
    """Identifica páginas principalmente raster, SIN OCR ni extraer imágenes.

    Un sello o logotipo pequeño no debe provocar OCR. Si se rebasa el
    límite se informa cobertura desconocida en lugar de declarar éxito.
    Devuelve (páginas 1-based, páginas sin inspeccionar, páginas inciertas).
    """
    raster, inciertas = [], []
    with fitz.open(stream=contenido, filetype="pdf") as pdf:
        maximo = min(len(pdf), limite_inspeccion)
        for idx in range(maximo):
            pagina = pdf[idx]
            area = max(float(pagina.rect.get_area()), 1.0)
            try:
                imagenes = pagina.get_image_info()
                cobertura = sum(
                    fitz.Rect(img["bbox"]).intersect(pagina.rect).get_area()
                    for img in imagenes if "bbox" in img
                ) / area
            except (RuntimeError, ValueError, KeyError, TypeError):
                inciertas.append(idx + 1)
                continue
            if cobertura >= 0.58:
                raster.append(idx + 1)
        restantes = max(0, len(pdf) - limite_inspeccion)
    return raster, restantes, inciertas


def _combinar_nominas_hibridas(nativas, escaneadas, paginas_objetivo):
    """Conserva trabajadores nativos y agrega solo páginas raster revisadas.

    Si dos lectores entregan días positivos distintos para igual RUT, página
    e institución, el número se ANULA para revisión: jamás elegir uno.
    """
    import copy
    resultado = copy.deepcopy(nativas)
    indexados = {}
    for anexo in resultado:
        for fila in anexo.get("trabajadores", []):
            clave = (
                anexo.get("pagina"), anexo.get("institucion_salud"),
                fila.get("trabajador_rut"),
            )
            indexados[clave] = fila
    leidas = set()
    conflictos = 0
    for anexo in escaneadas:
        pagina = anexo.get("pagina")
        if pagina not in paginas_objetivo:
            continue
        trabajadores = []
        for fila in anexo.get("trabajadores", []):
            clave = (
                pagina, anexo.get("institucion_salud"),
                fila.get("trabajador_rut"),
            )
            previo = indexados.get(clave)
            if previo is None:
                trabajadores.append(fila)
                indexados[clave] = fila
                continue
            antiguo = previo.get("dias_trabajados_fonasa")
            nuevo = fila.get("dias_trabajados_fonasa")
            if (
                isinstance(antiguo, int) and isinstance(nuevo, int)
                and antiguo != nuevo
            ):
                conflictos += 1
                previo["dias_trabajados_fonasa"] = None
                previo["dias_requieren_revision"] = True
                previo["observacion_dias"] = (
                    "Texto PDF y OCR discrepan: días requieren revisión."
                )
                for traza in previo.get("traza_dias", []):
                    traza["valor"] = None
                    traza["metodo"] = "conflicto_ocr_hibrido"
        if trabajadores:
            copia = dict(anexo)
            copia["trabajadores"] = trabajadores
            resultado.append(copia)
        if anexo.get("trabajadores"):
            leidas.add(pagina)
    return resultado, leidas, conflictos


def _extraer_hibrido(contenido, digital, *, paginas_candidatas,
                     instituciones_candidatas, diagnostico,
                     usar_ocr_alternativo, inicio):
    """Ejecuta OCR únicamente cuando hay páginas raster junto a texto nativo."""
    paginas_raster, sin_inspeccionar, inciertas = _paginas_raster(contenido)
    paginas_digitales = {a.get("pagina") for a in digital}
    candidatas = [
        p for p in sorted(set(paginas_raster + inciertas))
        if p not in paginas_digitales
    ]
    limite_ocr = 8  # Control explícito de memoria / duración del servidor.
    por_analizar = candidatas[:limite_ocr]
    pendientes = set(candidatas[limite_ocr:])
    resultado = digital
    leidas = set()
    conflictos = 0
    error_ocr = ""
    if por_analizar:
        try:
            lector = cargar_lector_fonasa()
            lectura = lector.extraer_nomina_fonasa(
                contenido,
                paginas_candidatas=por_analizar,
                instituciones_candidatas=instituciones_candidatas,
                usar_ocr_alternativo=usar_ocr_alternativo,
            )
            if lectura and not _nomina_tiene_traza(lectura):
                raise RuntimeError("OCR híbrido devolvió días sin traza")
            resultado, leidas, conflictos = _combinar_nominas_hibridas(
                digital, lectura, set(por_analizar)
            )
        except Exception as exc:
            # No borrar trabajadores verificados digitalmente por una caída
            # del OCR; sí dejar constancia de lectura PARCIAL y error real.
            error_ocr = f"{type(exc).__name__}: {str(exc)[:150]}"
            pendientes.update(por_analizar)
    pendientes.update(set(por_analizar) - leidas)
    if diagnostico is not None:
        diagnostico.update({
            "ruta": "texto_pdf_mas_ocr_hibrido",
            "paginas_imagen": paginas_raster,
            "paginas_ocr_intentadas": por_analizar,
            "paginas_pendientes": sorted(pendientes),
            "paginas_sin_inspeccionar": sin_inspeccionar,
            "cobertura_parcial": bool(
                pendientes or sin_inspeccionar or conflictos or error_ocr
            ),
            "conflictos_ocr": conflictos,
            "error_ocr_hibrido": error_ocr,
            "duracion_segundos": round(time.perf_counter() - inicio, 3),
            "trabajadores_encontrados": sum(
                len(a.get("trabajadores", [])) for a in resultado
            ),
            "segundo_motor_habilitado": bool(usar_ocr_alternativo),
        })
    return resultado


def extraer_fonasa_con_contrato(contenido: bytes, *, paginas_candidatas=None,
                                instituciones_candidatas=None,
                                diagnostico=None, usar_ocr_alternativo=False):
    """OCR primero en páginas conocidas; rescate geométrico solo si falla.

    La etapa rápida no requiere identificar un recibo. Si el OCR produce
    personas sin traza, se rechaza antes de devolver valores inventados.
    """
    inicio = time.perf_counter()
    # Prioridad P0: la capa de texto vectorial del PDF es MÁS precisa y
    # rápida que rasterizar/Tesseract. Soporta planillas cortas (1-5 personas),
    # que el detector OpenCV antiguo rechazaba por exigir 6+ líneas.
    from planillas_texto_digital import extraer_nominas_pdf_texto
    try:
        resultado_digital = extraer_nominas_pdf_texto(
            contenido, paginas_candidatas=paginas_candidatas,
            instituciones_candidatas=instituciones_candidatas,
        )
    except (fitz.FileDataError, ValueError):
        # Los tests históricos pasan bytes simulados, no PDF válidos. En
        # producción un PDF corrupto seguirá fallando en la ruta OCR.
        resultado_digital = []
    fuente_salud_confirmada = any(
        x.get("institucion_salud") == "Fonasa"
        or str(x.get("institucion_salud", "")).startswith("Isapre")
        for x in resultado_digital
    )
    if fuente_salud_confirmada and _nomina_tiene_traza(resultado_digital):
        # No terminar silenciosamente después de la primera planilla digital:
        # un mismo PDF puede tener otras nóminas escaneadas.
        return _extraer_hibrido(
            contenido, resultado_digital,
            paginas_candidatas=paginas_candidatas,
            instituciones_candidatas=instituciones_candidatas,
            diagnostico=diagnostico,
            usar_ocr_alternativo=usar_ocr_alternativo,
            inicio=inicio,
        )
    # Seguro Social sin Fonasa es una referencia útil, pero NO impide que
    # exista una planilla de salud escaneada más adelante: buscar con OCR.
    referencia_seguro_social = resultado_digital
    modulo = cargar_lector_fonasa()
    nomina = modulo.extraer_nomina_fonasa(
        contenido, paginas_candidatas=paginas_candidatas,
        instituciones_candidatas=instituciones_candidatas,
        usar_ocr_alternativo=usar_ocr_alternativo,
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
                usar_ocr_alternativo=usar_ocr_alternativo,
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
                usar_ocr_alternativo=usar_ocr_alternativo,
            )
    if nomina and not _nomina_tiene_traza(nomina):
        importlib.invalidate_caches()
        modulo = importlib.reload(modulo)
        if not _contrato_valido(modulo):
            raise RuntimeError("Salud: bytecode OCR desactualizado tras recarga.")
        nomina = modulo.extraer_nomina_fonasa(
            contenido, paginas_candidatas=paginas_candidatas,
            instituciones_candidatas=instituciones_candidatas,
            usar_ocr_alternativo=usar_ocr_alternativo,
        )
        if not _nomina_tiene_traza(nomina):
            raise RuntimeError(
                "Salud: no hay traza de días por trabajador después "
                "de repetir el OCR; no mostrar días sin procedencia."
            )
    if not nomina and referencia_seguro_social:
        # Si no existe una nómina de salud recuperada, entregar únicamente
        # los días documentados por Seguro Social como REFERENCIA PENDIENTE.
        nomina = referencia_seguro_social
        modo = "texto_seguro_social_sin_planilla_salud"
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
