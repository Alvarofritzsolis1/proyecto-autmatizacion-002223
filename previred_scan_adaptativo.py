"""OCR geométrico de PREVIRED escaneado (GALANT v18).

Rota hojas de lado, busca separadores reales de tablas y lee RUT, base y
días por celda. El cero del Fondo AFP nunca se reemplaza por la renta de
Seguro de Cesantía. Un documento desconocido retorna None sin inventar datos.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
import re

import cv2
import fitz
import numpy as np
import pandas as pd
from PIL import Image, ImageOps
from previred_pdf import _rut_clean, _rut_ok

PERFILES = {
    "salud": {"rut": (1, 2), "nombre": (2, 5),
              "dias": (5, 6), "base": (7, 8)},
    "seguro_social": {"rut": (1, 2), "nombre": (2, 3),
                      "base": (3, 4), "dias": (9, 10)},
    "afp": {"rut": (0, 1), "nombre": (1, 2),
            "base": (2, 3), "cesantia": (9, 10)},
    "mutual": {"rut": (0, 1), "nombre": (1, 4), "base": (4, 5)},
}


@dataclass
class Anexo:
    tipo: str
    pagina: int
    imagen: Image.Image
    filas: list[tuple[int, int]]
    separadores: list[int]
    periodo: str
    folio: str


def _ocr(imagen, config="--psm 6", timeout=5):
    import pytesseract
    try:
        return pytesseract.image_to_string(
            imagen, lang="eng", config="--oem 1 " + config, timeout=timeout
        ).strip()
    except (OSError, RuntimeError):
        return ""


def _horizontal(pagina, escala=2.3):
    pix = pagina.get_pixmap(
        matrix=fitz.Matrix(escala, escala), colorspace=fitz.csGRAY, alpha=False
    )
    imagen = Image.frombytes("L", (pix.width, pix.height), pix.samples)
    if imagen.height > imagen.width:
        imagen = imagen.rotate(90, expand=True)
    return imagen


def _tipo(texto):
    t = texto.lower()
    if "seguro social" in t and "previsional" in t:
        return "seguro_social"
    if "fonasa" in t or ("anexos de detalle" in t and "cotizacion 7" in t):
        return "salud"
    if "achs" in t or "asociacion chilena de seguridad" in t:
        return "mutual"
    if ("afp" in t or "fondo de pensiones" in t) and "detalle" in t:
        return "afp"
    return ""


def _agrupar(indices, salto=2):
    grupos = []
    for v in indices:
        n = int(v)
        if not grupos or n > grupos[-1][-1] + salto:
            grupos.append([n])
        else:
            grupos[-1].append(n)
    return grupos


def _filas(imagen):
    pix = np.asarray(imagen)
    alto, ancho = pix.shape
    mascara = cv2.threshold(pix, 175, 255, cv2.THRESH_BINARY_INV)[1]
    horizontal = cv2.morphologyEx(
        mascara, cv2.MORPH_OPEN,
        cv2.getStructuringElement(
            cv2.MORPH_RECT, (max(36, int(ancho * .045)), 1)
        )
    )
    contornos, _ = cv2.findContours(
        horizontal, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE
    )
    lineas = []
    for contorno in contornos:
        x, y, w, h = cv2.boundingRect(contorno)
        if w >= ancho * .80 and alto * .15 < y < alto * .52 and h < 25:
            lineas.append(y)
    lineas = sorted(set(lineas))
    cadenas = []
    for i in range(len(lineas)):
        actual = [lineas[i]]
        for linea in lineas[i + 1:]:
            salto = linea - actual[-1]
            if 12 <= salto <= 31:
                actual.append(linea)
            else:
                break
        if len(actual) >= 3:
            cadenas.append(actual)
    if not cadenas:
        return []
    mejor = max(cadenas, key=lambda xs: (len(xs), -xs[0]))
    return list(zip(mejor[:-1], mejor[1:])) if len(mejor) <= 120 else []


def _columnas(imagen, filas):
    a = np.asarray(imagen)
    alto, ancho = a.shape
    ya, yb = filas[0][0], filas[-1][1]
    recorte = (a[max(0, ya-2):min(alto, yb+2)] < 170).astype("uint8") * 255
    largo = max(10, min(24, int((yb-ya) * .35)))
    verticales = cv2.morphologyEx(
        recorte, cv2.MORPH_OPEN,
        cv2.getStructuringElement(cv2.MORPH_RECT, (1, largo))
    )
    xs = np.flatnonzero(verticales.sum(axis=0) / 255 > (yb-ya) * .38)
    bordes = [int(round(np.median(grupo))) for grupo in _agrupar(xs)]
    if len(bordes) < 9 or bordes[0] > ancho * .10 or bordes[-1] < ancho * .8:
        return []
    return bordes


def _celda(anexo, indice, campo, escala):
    spec = PERFILES[anexo.tipo].get(campo)
    if spec is None or spec[1] >= len(anexo.separadores):
        return None
    x1, x2 = anexo.separadores[spec[0]], anexo.separadores[spec[1]]
    y1, y2 = anexo.filas[indice]
    crop = anexo.imagen.crop((x1+5, y1+7, x2-5, y2+8))
    if crop.width < 8 or crop.height < 8:
        return None
    crop = crop.resize(
        (int(crop.width*escala), int(crop.height*escala)),
        Image.Resampling.BICUBIC
    )
    return ImageOps.autocontrast(crop)


def _numero(texto):
    limpio = re.sub(r"[^0-9.]", "", texto or "")
    if not re.fullmatch(r"\d{1,3}(?:\.\d{3})+|\d+", limpio):
        return None
    return int(limpio.replace(".", ""))


def _leer_fila(anexo, indice):
    ruts, bases, dias, cesantia = [], [], [], []
    for escala in (3, 4.2):
        for campo, salida in (
            ("rut", ruts), ("base", bases), ("dias", dias),
            ("cesantia", cesantia)
        ):
            crop = _celda(anexo, indice, campo, escala)
            if crop is None:
                continue
            cfg = ("--psm 7 -c tessedit_char_whitelist=0123456789.K-"
                   if campo == "rut" else
                   "--psm 7 -c tessedit_char_whitelist=0123456789.")
            texto = _ocr(crop, cfg, timeout=4)
            if campo == "rut":
                limpio = re.sub(r"[^0-9K]", "", texto.upper())
                if len(limpio) in (8, 9):
                    salida.append(limpio)
            else:
                num = _numero(texto)
                if num is not None:
                    salida.append(num)
    if anexo.tipo == "afp" and not bases:
        # Un cero AFP junto al borde no se debe reemplazar por Cesantía.
        borde = anexo.separadores[PERFILES["afp"]["base"][1]]
        y1, y2 = anexo.filas[indice]
        glifo = anexo.imagen.crop((borde-16, y1+6, borde, y2+8))
        glifo = ImageOps.autocontrast(
            glifo.resize((glifo.width*8, glifo.height*8))
        )
        imagen = Image.new("L", (glifo.width+45, glifo.height+45), 255)
        imagen.paste(glifo, (20, 20))
        if any(x.strip().strip("_.,| ") == "0" for x in (
            _ocr(imagen, "--psm 7"), _ocr(imagen, "--psm 10")
        )):
            bases = [0, 0]
    nombre = ""
    if anexo.tipo == "salud":
        partes = []
        for izq, der in ((2, 3), (3, 4), (4, 5)):
            y1, y2 = anexo.filas[indice]
            xs = anexo.separadores
            crop = anexo.imagen.crop((xs[izq]+4, y1+6, xs[der]-4, y2+8))
            crop = ImageOps.autocontrast(
                crop.resize((crop.width*4, crop.height*4))
            )
            pal = _ocr(crop, "--psm 7")
            pal = " ".join(re.findall(
                r"[A-Za-zÁÉÍÓÚÑÜáéíóúñü]+", pal
            )).upper()
            if pal and (len(pal) >= 3 or pal in {"DE", "LA"}):
                partes.append(pal)
        nombre = " ".join(partes)
    return {
        "pagina": anexo.pagina, "tipo": anexo.tipo,
        "ruts": ruts, "bases": bases,
        "dias": dias, "cesantia": cesantia, "nombre": nombre,
    }


def _mas_comun(valores):
    if not valores:
        return None
    c = Counter(valores)
    return max(c, key=lambda x: (c[x], x))


def _rut_validado(obs, anclas):
    validos = [r for r in obs["ruts"] if _rut_ok(r)]
    if validos:
        c = Counter(validos)
        return max(c, key=lambda x: (c[x], x in anclas))
    opciones = [
        rut for crudo in obs["ruts"] for rut in anclas
        if len(crudo) == len(rut)
        and sum(a != b for a, b in zip(crudo, rut)) <= 1
    ]
    return opciones[0] if len(set(opciones)) == 1 else ""


def _anexos(pdf):
    anexos, problemas = [], []
    if pdf.page_count > 120:
        raise ValueError("Documento demasiado largo para OCR interactivo.")
    for i, page in enumerate(pdf):
        if len(page.get_text().strip()) > 120:
            return [], []  # conservar lectura digital más precisa
        img = _horizontal(page)
        w, h = img.size
        cabecera = _ocr(img.crop((0, 0, w, int(h*.24))), "--psm 6")
        tipo = _tipo(cabecera)
        if not tipo:
            continue
        if (tipo != "seguro_social" and "detalle" not in cabecera.lower()
                and "anexos" not in cabecera.lower()):
            continue
        filas = _filas(img)
        if not filas:
            problemas.append(f"p.{i+1}: no se recuperaron filas {tipo}")
            continue
        separadores = _columnas(img, filas)
        if not separadores:
            problemas.append(f"p.{i+1}: no se recuperaron columnas {tipo}")
            continue
        if any(PERFILES[tipo][campo][1] >= len(separadores)
               for campo in ("rut", "base")):
            problemas.append(f"p.{i+1}: columnas incompletas {tipo}")
            continue
        m = re.search(
            r"(?:per[ií]?od\w*\s+de\s+remuneraciones?)\s*[:;]?\s*"
            r"(0?[1-9]|1[0-2])\s*[/.-]\s*(20\d{2})",
            cabecera, re.I
        )
        periodo = f"{m.group(2)}-{int(m.group(1)):02d}" if m else ""
        folio = re.search(r"(\d{13,18})", cabecera)
        anexos.append(Anexo(
            tipo, i+1, img, filas, separadores, periodo,
            folio.group(1) if folio else ""
        ))
    return anexos, problemas


def extraer_previred_scan_adaptativo(contenido: bytes, nombre: str):
    """Leer por celda; si el perfil es desconocido, activar otro extractor."""
    with fitz.open(stream=contenido, filetype="pdf") as pdf:
        anexos, problemas = _anexos(pdf)
    tipos = {a.tipo for a in anexos}
    if not {"salud", "mutual"}.issubset(tipos) or not (
        {"afp", "seguro_social"} & tipos
    ):
        return None
    observaciones = []
    for a in anexos:
        for i in range(len(a.filas)):
            obs = _leer_fila(a, i)
            if obs["ruts"] or obs["bases"]:
                observaciones.append(obs)
    anclas = {
        r for obs in observaciones for r in obs["ruts"] if _rut_ok(r)
    }
    if len(anclas) < 2:
        return None
    agrupado = defaultdict(lambda: defaultdict(list))
    nombres, incidencias, sin_rut = {}, defaultdict(list), []
    for obs in observaciones:
        rut = _rut_validado(obs, anclas)
        if not rut:
            sin_rut.append(
                f"p.{obs['pagina']}: RUT ilegible en {obs['tipo']}"
            )
            continue
        agrupado[rut][obs["tipo"]].append(obs)
        if obs["nombre"] and len(obs["nombre"]) > 8:
            nombres[rut] = obs["nombre"]
    if not agrupado:
        return None
    for rut, fuentes in agrupado.items():
        consenso = Counter(
            valor for filas in fuentes.values() for dato in filas
            for valor in dato["bases"] if valor > 0
        )
        for filas in fuentes.values():
            for dato in filas:
                alternativas = list(dict.fromkeys(dato["bases"]))
                cotejadas = [v for v in alternativas if consenso[v] >= 2]
                dato["base_elegida"] = (
                    cotejadas[0] if len(cotejadas) == 1
                    else _mas_comun(dato["bases"])
                )
                if len(alternativas) > 1 and not cotejadas:
                    incidencias[rut].append(
                        f"p.{dato['pagina']}: alternativas OCR {alternativas}"
                    )
                dias = [n for n in dato["dias"] if 0 <= n <= 31]
                dato["dias_elegidos"] = _mas_comun(dias)
    periodos = {a.periodo for a in anexos if a.periodo}
    periodo = next(iter(periodos)) if len(periodos) == 1 else ""
    if len(periodos) > 1:
        problemas.append("Períodos distintos entre anexos")
    salud = next(a for a in anexos if a.tipo == "salud")
    w, h = salud.imagen.size
    cab = _ocr(salud.imagen.crop((
        int(w*.10), int(h*.15), int(w*.53), int(h*.25)
    )).resize((int(w*.86), int(h*.20))), "--psm 6")
    rm = re.search(
        r"\d{1,2}[. ]?\d{3}[. ]?\d{3}\s*[-–]\s*[0-9Kk]", cab
    )
    rut_empresa = (
        _rut_clean(rm.group()) if rm and _rut_ok(_rut_clean(rm.group()))
        else ""
    )
    nm = re.search(
        r"(?:RAZON\s+SOCIAL\s+O\s+)?NOMBRE\s+(.+)", cab, re.I
    )
    empresa = (
        nm.group(1).splitlines()[0].strip(" _.").upper() if nm
        else "CONTRATISTA NO IDENTIFICADO"
    )
    salida = []
    for rut, fuentes in sorted(agrupado.items()):
        def total(tipo, campo):
            valores = [dato.get(campo) for dato in fuentes.get(tipo, [])]
            return sum(valores) if (
                valores and all(v is not None for v in valores)
            ) else None
        sal = total("salud", "base_elegida")
        afp = total("afp", "base_elegida")
        mut = total("mutual", "base_elegida")
        ss = total("seguro_social", "base_elegida")
        ds = total("salud", "dias_elegidos")
        dss = total("seguro_social", "dias_elegidos")
        notas = list(dict.fromkeys(incidencias[rut]))
        if not periodo:
            notas.append("Período no confirmado en cabeceras")
        if not rut_empresa:
            notas.append("RUT empleador no confirmado en cabecera")
        for tipo, valor in (("Salud", sal), ("Mutual", mut), ("AFP", afp)):
            if valor is None:
                notas.append(f"Falta base individual {tipo}")
        if afp == 0 and sal and sal > 0:
            ces = sum(
                _mas_comun(dato["cesantia"]) or 0
                for dato in fuentes.get("afp", [])
            )
            notas.append(
                f"AFP Fondo de Pensiones cero; Salud {sal:,} CLP; "
                f"Seguro de Cesantía {ces:,} CLP. Verificar exención o régimen"
            )
        if ds is not None and dss is not None and ds != dss:
            notas.append("Días Salud distintos de Seguro Social")
        if sal is not None and mut is not None and sal != mut:
            notas.append("Bases Salud y Mutual distintas")
        if sal is not None and afp is not None and afp > 0 and sal != afp:
            notas.append("Bases AFP y Salud distintas")
        paginas = sorted({
            obs["pagina"] for filas in fuentes.values() for obs in filas
        })
        salida.append({
            "periodo_remuneracion": periodo,
            "contratista_nombre": empresa,
            "contratista_rut": rut_empresa,
            "trabajador_nombre": nombres.get(
                rut, "NOMBRE EN REVISION OCR"
            ),
            "trabajador_rut": rut,
            "dias_reales_pagados": ds if ds is not None else dss,
            "renta_imponible_salud": sal,
            "renta_imponible_afp": afp,
            "renta_imponible_mutual": mut,
            "mutual_adherida": "ACHS",
            "__hoja_origen": ", ".join(f"p.{p}" for p in paginas),
            "__conflicto_pdf": "; ".join(notas),
            "__cobertura_seguro_social": (
                "PRESENTE_SS" if ss is not None else "SIN_REGISTRO_SS"
            ),
            "__renta_seguro_social": ss,
            "__ocr_evidencia": "Fuentes: " + ", ".join(sorted(fuentes)),
            "__observaciones_archivo": "; ".join(problemas + sin_rut),
        })
    df = pd.DataFrame(salida)
    df.attrs["diagnostico_ocr"] = {
        "paginas_detectadas": [a.pagina for a in anexos],
        "fuentes_detectadas": sorted(tipos),
        "rut_sin_asignar": sin_rut,
        "filas_por_pagina": {a.pagina: len(a.filas) for a in anexos},
    }
    return df
