"""Segundo OCR gratuito para comprobantes PREVIRED escaneados.

RapidOCR/ONNX se carga únicamente si se activa la casilla de rescate.
No envía PDF a ningún servicio externo. La segunda lectura NUNCA
confirma por sí sola el pago ni la cobertura de todos los folios.
"""
from __future__ import annotations

from functools import lru_cache
import re
import threading
import unicodedata

import fitz
from PIL import Image

_LOCK = threading.RLock()
_FECHA = re.compile(r"(?<!\d)([0-3]?\d\s*[/.-]\s*[01]?\d\s*[/.-]\s*20\d{2})(?!\d)")
_PERIODO = re.compile(r"(?<!\d)(0?[1-9]|1[0-2])\s*[/.-]\s*(20\d{2})(?!\d)")
_ANO = re.compile(r"\b20\d{2}\b")
_MES = re.compile(r"(?<!\d)(0?[1-9]|1[0-2])(?!\d)")


def _normal(texto: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", texto)
                   if unicodedata.category(c) != "Mn").lower()


@lru_cache(maxsize=1)
def _motor():
    from rapidocr import RapidOCR
    return RapidOCR()


def _lineas(resultado, ancho: int, alto: int) -> list[dict]:
    raw_textos = getattr(resultado, "txts", None)
    textos = list(raw_textos) if raw_textos is not None else []
    cajas = getattr(resultado, "boxes", None)
    raw_confianzas = getattr(resultado, "scores", None)
    confianzas = list(raw_confianzas) if raw_confianzas is not None else []
    if cajas is None:
        return []
    salida = []
    for i, texto in enumerate(textos):
        if i >= len(cajas) or not str(texto).strip():
            continue
        confianza = float(confianzas[i]) if i < len(confianzas) else 0.0
        if confianza < .42:
            continue
        puntos = cajas[i]
        xs = [float(p[0]) for p in puntos]
        ys = [float(p[1]) for p in puntos]
        salida.append({
            "texto": str(texto).strip(), "confianza": confianza,
            "x": min(xs) / ancho, "y": min(ys) / alto,
            "x_fin": max(xs) / ancho, "y_fin": max(ys) / alto,
        })
    return sorted(salida, key=lambda r: (round(r["y"], 2), r["x"]))


def _fecha_cuadro(lineas: list[dict]) -> str:
    """Exige etiqueta 'Pago Electrónico' y proximidad visual de la fecha."""
    for i, r in enumerate(lineas):
        t = _normal(r["texto"])
        if not re.search(r"pago\s*electr\w{2,12}", t):
            continue
        directa = _FECHA.search(t)
        if directa:
            return re.sub(r"\s+", "", directa.group(1)).replace(".", "/").replace("-", "/")
        posibles = []
        for j, otra in enumerate(lineas):
            if i == j:
                continue
            f = _FECHA.search(_normal(otra["texto"]))
            if not f:
                continue
            dy = otra["y"] - r["y"]
            dx = abs(otra["x"] - r["x"])
            if -.018 <= dy <= .095 and dx < .24:
                posibles.append((max(dy, 0), dx, f.group(1)))
        if posibles:
            f = min(posibles)[2]
            return re.sub(r"\s+", "", f).replace(".", "/").replace("-", "/")
    return ""


def _periodo_casillas(lineas: list[dict]) -> str:
    """No tomar las fechas de inicio/fin de trabajadores como período."""
    anclas = [r for r in lineas if re.search(
        r"\bperi[o0l1]do\b|periodo|remuneracion", _normal(r["texto"])
    )]
    for a in anclas:
        contexto = [r for r in lineas if
                    abs(r["y"] - a["y"]) < .10
                    and abs(r["x"] - a["x"]) < .50]
        contexto = sorted(contexto, key=lambda r: (r["y"], r["x"]))
        for r in contexto:
            m = _PERIODO.search(_normal(r["texto"]))
            if m:
                return f"{m.group(2)}-{int(m.group(1)):02d}"
        # El mes y el año aparecen en casillas distintas (ej. Kohle).
        anios = [r for r in contexto if _ANO.fullmatch(r["texto"].strip())]
        meses = [r for r in contexto if _MES.fullmatch(r["texto"].strip())]
        pares = [
            (abs(m["y"] - y["y"]), f"{y['texto']}-{int(m['texto']):02d}")
            for y in anios for m in meses
            if m["x"] < y["x"] and abs(m["y"] - y["y"]) < .022
            and y["y"] >= a["y"] - .025
        ]
        if pares:
            pares.sort()
            mejores = {v for dif, v in pares if dif <= pares[0][0] + .006}
            if len(mejores) == 1:
                return next(iter(mejores))
    return ""


def _datos(lineas: list[dict]) -> dict:
    from pago_documental import _folio, _institucion, _periodo, _interpretar
    texto = "\n".join(x["texto"] for x in lineas)
    # El orden del OCR no siempre sigue el orden visual: priorizar coordenadas.
    fecha = _fecha_cuadro(lineas)
    periodo = _periodo_casillas(lineas)
    if not periodo and re.search(r"\bperiodo\b", _normal(texto)):
        periodo = _periodo(texto)
    folio = _folio(texto)
    institucion = _institucion(texto)
    cuenta_pago = bool(re.search(r"pago\s*electr\w{2,12}", _normal(texto)))
    return {"texto": texto, "fecha_pago": fecha, "periodo": periodo,
            "folio": folio, "institucion": institucion,
            "cuadro_pago": cuenta_pago,
            "plantilla": bool(_interpretar(texto, 1, "RapidOCR"))}


def leer_pagina(pagina: fitz.Page, orientacion=None, engine=None) -> dict:
    """CPU limitado; un motor compartido, una inferencia a la vez por proceso."""
    pix = pagina.get_pixmap(matrix=fitz.Matrix(1.65, 1.65),
                            colorspace=fitz.csRGB, alpha=False)
    imagen = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
    imagen.thumbnail((1900, 1900), Image.Resampling.LANCZOS)
    if orientacion in (0, 90, 180, 270):
        giros = [orientacion]
    elif imagen.height > imagen.width:
        giros = [90, 270]
    else:
        giros = [0, 180]
    resultado_mejor = None
    puntaje_mejor = -1
    for giro in giros[:2]:
        vista = imagen.rotate(giro, expand=True) if giro else imagen
        with _LOCK:
            lector = engine if engine is not None else _motor()
            salida = lector(vista)
        lineas = _lineas(salida, vista.width, vista.height)
        datos = _datos(lineas)
        puntaje = (
            3 * bool(datos["fecha_pago"])
            + 3 * bool(datos["periodo"])
            + 2 * bool(datos["folio"])
            + int(datos["plantilla"])
            + int(datos["cuadro_pago"])
        )
        if puntaje > puntaje_mejor:
            resultado_mejor, puntaje_mejor = datos, puntaje
        if puntaje >= 8:
            break
    return resultado_mejor or {
        "texto": "", "fecha_pago": "", "periodo": "",
        "folio": "", "institucion": "Institución no identificada",
        "cuadro_pago": False, "plantilla": False,
    }


def _pendiente(e: dict) -> bool:
    return (not e.get("fecha_pago") or not e.get("periodo")
            or not e.get("folio")
            or "no identificada" in str(e.get("institucion", "")).lower()
            or e.get("conflicto_fecha_ocr"))


def _unir(e: dict, nuevo: dict) -> None:
    """En página única, comparar folio antes de unir; no inventar aprobación."""
    if not nuevo.get("cuadro_pago") and not nuevo.get("plantilla"):
        return
    a = str(e.get("folio", ""))
    b = str(nuevo.get("folio", ""))
    if a and b and a != b:
        e["conflicto_folio_rapidocr"] = True
        e["estado"] = "EVIDENCIA_INSUFICIENTE"
        e["observacion"] = (
            str(e.get("observacion", "")) + " | Diferentes folios entre OCR: revisar."
        ).strip(" |")
        return
    a_inst = str(e.get("institucion", ""))
    b_inst = str(nuevo.get("institucion", ""))
    if (a_inst and b_inst and "no identificada" not in a_inst.lower()
        and "no identificada" not in b_inst.lower() and a_inst != b_inst):
        e["conflicto_institucion_rapidocr"] = True
        e["estado"] = "EVIDENCIA_INSUFICIENTE"
        return
    # Falta de folio en un motor NO acredita que ambos estén leyendo la
    # misma institución. Se conservan datos como candidatos, pero se fuerza
    # revisión en pantalla y nunca aprobación documental automática.
    if (a and not b) or (b and not a):
        e["rapidocr_folio_no_corrobado"] = True
        e["estado"] = "EVIDENCIA_INSUFICIENTE"
        e["observacion"] = (
            str(e.get("observacion", ""))
            + " | No se pudo corroborar el folio entre ambos OCR."
        ).strip(" |")
    for campo in ("folio", "institucion", "periodo", "fecha_pago"):
        valor = nuevo.get(campo, "")
        actual = e.get(campo, "")
        falta = not actual or (
            campo == "institucion" and "no identificada" in str(actual).lower()
        )
        if falta and valor and "no identificada" not in str(valor).lower():
            if campo == "fecha_pago" and not nuevo.get("cuadro_pago"):
                continue
            e[campo] = valor
        elif not falta and valor and str(actual) != str(valor):
            e["conflicto_" + campo + "_rapidocr"] = True
            e["estado"] = "EVIDENCIA_INSUFICIENTE"
            e["observacion"] = (
                str(e.get("observacion", ""))
                + " | Dato contradictorio entre Tesseract y RapidOCR."
            ).strip(" |")
    e["fuente_rescate"] = "RapidOCR (comparación visual)"
    if not a and nuevo.get("folio") and not b_inst:
        e["estado"] = "EVIDENCIA_INSUFICIENTE"
    # No elevar el estado a PAGADO por OCR alternativo, ni borrar alertas.


def rescatar(contenido: bytes, evidencias: list[dict], *,
            max_paginas: int = 2, engine=None) -> dict:
    """OCR adicional acotado; nunca interpreta falta de OCR como impago."""
    resumen = {"estado": "sin_necesidad", "paginas": [],
               "errores": 0, "comprobantes_adicionales": 0}
    pendientes = [e["pagina"] for e in evidencias if _pendiente(e)]
    with fitz.open(stream=contenido, filetype="pdf") as pdf:
        escaneadas = [
            i + 1 for i, p in enumerate(pdf)
            if len(p.get_text("text").strip()) < 90
        ]
        if not pendientes and not evidencias:
            pendientes = escaneadas[::2] or escaneadas
        paginas = [p for p in dict.fromkeys(pendientes)
                   if p in escaneadas][:max(0, min(max_paginas, 3))]
        if not paginas:
            return resumen
        resumen["estado"] = "ejecutado"
        for n in paginas:
            resumen["paginas"].append(n)
            try:
                datos = leer_pagina(pdf[n-1], engine=engine)
            except (ImportError, RuntimeError, ValueError, OSError):
                resumen["errores"] += 1
                resumen["estado"] = "fallo_parcial"
                continue
            de_pagina = [e for e in evidencias if e["pagina"] == n]
            if len(de_pagina) == 1:
                _unir(de_pagina[0], datos)
            elif len(de_pagina) == 0 and datos["plantilla"]:
                from pago_documental import _interpretar
                nuevo = _interpretar(datos["texto"], n, "RapidOCR")
                if nuevo:
                    if datos["periodo"]:
                        nuevo["periodo"] = datos["periodo"]
                    if datos["fecha_pago"] and datos["cuadro_pago"]:
                        nuevo["fecha_pago"] = datos["fecha_pago"]
                    nuevo["estado"] = "EVIDENCIA_INSUFICIENTE"
                    nuevo["observacion"] = (
                        "Reconocido solo por OCR alternativo; falta "
                        "validar institución, folio y cobertura."
                    )
                    nuevo["fuente_rescate"] = "RapidOCR"
                    evidencias.append(nuevo)
                    resumen["comprobantes_adicionales"] += 1
    return resumen
