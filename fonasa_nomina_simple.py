"""Lectura SIMPLE de anexos Fonasa: nombre, RUT y días sin cuadre de imposiciones.

Solo se leen páginas candidatas de anexo. No se envían PDF a ninguna API.
Las líneas de movimientos con cero días NO crean trabajadores duplicados.
Un día no legible se devuelve como None, jamás como 0 ni como impago.
"""
from __future__ import annotations

import re
from collections import Counter, defaultdict

import cv2
import fitz
import numpy as np
from PIL import Image
import pytesseract


def normalizar_rut(texto):
    s = re.sub(r"[^0-9Kk]", "", str(texto)).upper()
    if len(s) not in (8, 9):
        return ""
    cuerpo, digito = s[:-1], s[-1]
    valor = 11 - sum(
        int(x) * (i % 6 + 2) for i, x in enumerate(cuerpo[::-1])
    ) % 11
    esperado = "0" if valor == 11 else "K" if valor == 10 else str(valor)
    if digito != esperado:
        return ""
    return f"{int(cuerpo):,}".replace(",", ".") + "-" + digito


def _grupos(numeros, salto=2):
    grupos = []
    for valor in numeros:
        n = int(valor)
        if grupos and n - grupos[-1][-1] <= salto:
            grupos[-1].append(n)
        else:
            grupos.append([n])
    return [int(round(np.median(g))) for g in grupos]


def _reticula(imagen):
    """Detecta filas y columnas SIN intentar interpretar montos de AFP o mutual."""
    ar = np.asarray(imagen)
    inv = cv2.threshold(
        ar, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU
    )[1]
    kernel = cv2.getStructuringElement(
        cv2.MORPH_RECT, (max(80, int(imagen.width * .10)), 1)
    )
    horiz = cv2.morphologyEx(inv, cv2.MORPH_OPEN, kernel)
    cuenta = np.count_nonzero(horiz, axis=1)
    indices = np.flatnonzero(
        (cuenta > imagen.width * .23)
        & (np.arange(imagen.height) > imagen.height * .18)
        & (np.arange(imagen.height) < imagen.height * .72)
    )
    ys = _grupos(indices)
    cadenas = []
    for i in range(len(ys)):
        secuencia = [ys[i]]
        for y in ys[i + 1:]:
            if 12 <= y - secuencia[-1] <= 34:
                secuencia.append(y)
            else:
                break
        if len(secuencia) >= 6:
            cadenas.append(secuencia)
    if not cadenas:
        return None
    filas = max(cadenas, key=len)
    region = inv[filas[0]:filas[-1]]
    vertical = cv2.morphologyEx(
        region, cv2.MORPH_OPEN,
        cv2.getStructuringElement(
            cv2.MORPH_RECT,
            (1, max(22, int((filas[-1] - filas[0]) * .13)))
        )
    )
    xs = _grupos(np.flatnonzero(
        np.count_nonzero(vertical, axis=0)
        > (filas[-1] - filas[0]) * .55
    ))
    if len(xs) < 7 or xs[0] > imagen.width * .10 or xs[6] < imagen.width * .5:
        return None
    return filas, xs


def _ocr_columna(imagen, filas, x0, x1):
    """Una sola llamada OCR por columna, en lugar de una por trabajador."""
    recorte = imagen.crop(
        (x0 + 4, filas[0] + 1, x1 - 3, filas[-1] - 1)
    )
    datos = pytesseract.image_to_data(
        recorte, lang="eng", config="--psm 6",
        timeout=9, output_type=pytesseract.Output.DICT
    )
    por_fila = defaultdict(list)
    for j, txt in enumerate(datos["text"]):
        txt = txt.strip()
        if not txt or float(datos["conf"][j]) < 22:
            continue
        centro = datos["top"][j] + datos["height"][j] / 2 + filas[0] + 1
        for k in range(len(filas) - 1):
            if filas[k] <= centro < filas[k + 1]:
                por_fila[k].append(txt)
                break
    return {i: " ".join(partes).strip() for i, partes in por_fila.items()}


def _nombres(columna, indices):
    opciones = []
    for i in indices:
        dato = re.sub(
            r"[^A-Za-zÁÉÍÓÚÑÜáéíóúñü\s]", "", columna.get(i, "")
        )
        dato = " ".join(dato.upper().split())
        if len(dato) >= 3:
            opciones.append(dato)
    return Counter(opciones).most_common(1)[0][0] if opciones else ""


def _grafia_celda_dias(imagen, x0, x1, y0, y1):
    """Corroboración geométrica para dígitos borrosos, sin asumir montos.

    En la planilla Fonasa escaneada, Tesseract interpretaba "11" como
    "2"/vacío y varias celdas "0" como "2". Esas lecturas creaban
    falsos días y anulaban el trabajador por conflicto.
    Solo confirmamos 11 si hay DOS trazos estrechos y similares.
    Un glifo cerrado (0/6/8/9) NO puede aceptarse como 1, 2 o 7.
    """
    alto = y1 - y0
    margen_y = max(2, round(alto * .12))
    margen_x = max(5, round(alto * .44))
    if x1 - x0 < 2 * margen_x + 10 or alto < 2 * margen_y + 7:
        return False, False
    region = np.asarray(imagen.convert("L").crop(
        (x0 + margen_x, y0 + margen_y, x1 - margen_x, y1 - margen_y)
    ))
    if not region.size:
        return False, False
    tinta = cv2.threshold(
        region, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU
    )[1]
    n, _, componentes, _ = cv2.connectedComponentsWithStats(tinta)
    glifos = []
    for k in range(1, n):
        x, y, ancho, altura, area = map(int, componentes[k])
        if (area < max(5, alto * .20)
                or altura < max(5, alto * .28)
                or ancho > alto * 1.15):
            continue
        mascara = tinta[y:y + altura, x:x + ancho]
        _, jerarquia = cv2.findContours(
            mascara, cv2.RETR_CCOMP, cv2.CHAIN_APPROX_SIMPLE
        )
        huecos = sum(
            1 for c in (jerarquia[0] if jerarquia is not None else [])
            if c[3] >= 0
        )
        glifos.append((x, y, ancho, altura, area, huecos))
    glifos.sort(key=lambda c: c[0])
    doble_uno = (
        len(glifos) == 2
        and all(c[2] / c[3] <= .55 and c[5] == 0 for c in glifos)
        and abs(glifos[0][1] - glifos[1][1]) < max(4, alto * .2)
        and .5 <= glifos[0][4] / glifos[1][4] <= 2.0
    )
    glifo_con_hueco = len(glifos) == 1 and glifos[0][5] >= 1
    return doble_uno, glifo_con_hueco


def _dias_celda(imagen, x0, x1, y0, y1, diagnostico=None):
    """Lee días con traza verificable, sin OCR adicional cuando se activa el diagnóstico.

    Una cifra sin confirmar NO se traduce a cero. Si Tesseract contradice la
    forma geométrica, registrar ambas lecturas para revisión en Streamlit.
    """
    doble_uno, glifo_con_hueco = _grafia_celda_dias(
        imagen, x0, x1, y0, y1
    )
    bruto = ""
    metodo = "sin_lectura"
    valor = None
    if doble_uno:
        valor = 11
        metodo = "dos_trazos_geometricos"
        # No se ejecuta Tesseract otra vez: la evidencia es la propia forma.
    else:
        from PIL import ImageOps
        recorte = imagen.crop((x0 + 9, y0 + 1, x1 - 7, y1 - 1))
        recorte = ImageOps.expand(recorte, border=10, fill=255)
        bruto = pytesseract.image_to_string(
            recorte, lang="eng",
            config="--psm 7 -c tessedit_char_whitelist=0123456789",
            timeout=4
        ).strip()
        if bruto.isdigit() and 0 <= int(bruto) <= 31:
            if int(bruto) == 0:
                metodo = "movimiento_cero"
            elif glifo_con_hueco and bruto in {"1", "2", "7"}:
                metodo = "rechazado_por_grafia_cerrada"
            else:
                valor = int(bruto)
                metodo = "ocr_numero"
        elif bruto:
            metodo = "texto_no_numerico"
    if diagnostico is not None:
        diagnostico.update({
            "ocr_bruto": bruto if not doble_uno else "(no requerido)",
            "dos_trazos": bool(doble_uno),
            "glifo_cerrado": bool(glifo_con_hueco),
            "valor": valor,
            "metodo": metodo,
            "celda_px": [int(x0), int(y0), int(x1), int(y1)],
        })
    return valor

def _nomina_de_imagen(imagen):
    geomet = _reticula(imagen)
    if not geomet:
        return []
    filas, columnas = geomet
    rut_col = _ocr_columna(imagen, filas, columnas[1], columnas[2])
    pat = _ocr_columna(imagen, filas, columnas[2], columnas[3])
    mat = _ocr_columna(imagen, filas, columnas[3], columnas[4])
    nombres = _ocr_columna(imagen, filas, columnas[4], columnas[5])
    rut_fila = [
        normalizar_rut(rut_col.get(i, ""))
        for i in range(len(filas) - 1)
    ]
    # El OCR puede leer mal solo la primera repetición del mismo RUT.
    # Recuperar ese primer registro únicamente si el siguiente lo valida.
    if len(rut_fila) > 1 and not rut_fila[0] and rut_fila[1]:
        rut_fila[0] = rut_fila[1]
    bloques = defaultdict(list)
    previo = ""
    for i, rut in enumerate(rut_fila):
        if rut:
            previo = rut
        if previo:
            bloques[previo].append(i)

    salida = []
    for rut, indices in bloques.items():
        apellido_paterno = _nombres(pat, indices)
        apellido_materno = _nombres(mat, indices)
        nombre = _nombres(nombres, indices)
        if not nombre or not apellido_paterno:
            continue
        valores_dias = []
        trazas = []
        for i in indices:
            y0, y1 = filas[i:i + 2]
            diagnostico = {"fila": int(i) + 1}
            dia = _dias_celda(
                imagen, columnas[5], columnas[6], y0, y1,
                diagnostico=diagnostico,
            )
            # El test de lectura simulada puede devolver un valor sin rellenar
            # diagnostico. Nunca ocultar cuál fue el valor utilizado.
            diagnostico.setdefault("valor", dia)
            diagnostico.setdefault("metodo", "lectura")
            trazas.append(diagnostico)
            if dia is not None:
                valores_dias.append(dia)
        # Si existen dos filas con días positivos, pueden representar
        # tramos distintos: no sumar ni escoger el máximo por suposición.
        dias_unicos = [v for v in valores_dias if v > 0]
        dias_confirmados = (
            dias_unicos[0] if len(dias_unicos) == 1 else None
        )
        salida.append({
            "trabajador_nombre": " ".join(
                x for x in (nombre, apellido_paterno, apellido_materno) if x
            ),
            "trabajador_rut": rut,
            "dias_trabajados_fonasa": dias_confirmados,
            "dias_requieren_revision": dias_confirmados is None,
            "filas_movimientos": len(indices),
            "traza_dias": trazas,
            "metodo_dias": (
                next(
                    (x.get("metodo", "sin_traza") for x in trazas
                     if x.get("valor") == dias_confirmados),
                    "sin_traza",
                ) if dias_confirmados is not None else "requiere_revision"
            ),
            "fuente": "Fonasa — anexo de detalle",
        })
    return salida


def _es_anexo_fonasa(pagina, orientacion):
    pix = pagina.get_pixmap(
        matrix=fitz.Matrix(1.25, 1.25), colorspace=fitz.csGRAY, alpha=False
    )
    im = Image.frombytes("L", (pix.width, pix.height), pix.samples)
    if orientacion:
        im = im.rotate(orientacion, expand=True)
    texto = pytesseract.image_to_string(
        im.crop((0, 0, im.width, int(im.height * .30))),
        lang="eng", config="--psm 11", timeout=5
    ).lower()
    return "fonasa" in texto and (
        "anexos" in texto or "detalle" in texto
    )


def extraer_nomina_fonasa(contenido, paginas_candidatas=None, max_paginas=18):
    """Lee solo candidatos (página del recibo Fonasa y siguiente anexo).

    No hace cuadraturas ni valida pagos. Esa tarea la cumple el lector separado
    de evidencia documental; nunca inferir impago porque falta una fila.
    """
    salida = []
    with fitz.open(stream=contenido, filetype="pdf") as pdf:
        indices = []
        if paginas_candidatas:
            for numero in paginas_candidatas:
                if not isinstance(numero, int):
                    continue
                for idx in (numero - 1, numero):
                    if 0 <= idx < len(pdf) and idx not in indices:
                        indices.append(idx)
        else:
            # Sin evidencia Fonasa conocida, búsqueda limitada y explícita.
            indices = list(range(min(max_paginas, len(pdf))))
        for idx in indices:
            pagina = pdf[idx]
            pix = pagina.get_pixmap(
                matrix=fitz.Matrix(1.0, 1.0),
                colorspace=fitz.csGRAY, alpha=False
            )
            girar = 90 if pix.height > pix.width else 0
            opciones = [girar, 270 if girar == 90 else 180]
            orientacion = next(
                (o for o in opciones if _es_anexo_fonasa(pagina, o)), None
            )
            if orientacion is None:
                continue
            pix = pagina.get_pixmap(
                matrix=fitz.Matrix(3, 3),
                colorspace=fitz.csGRAY, alpha=False
            )
            im = Image.frombytes("L", (pix.width, pix.height), pix.samples)
            if orientacion:
                im = im.rotate(orientacion, expand=True)
            filas = _nomina_de_imagen(im)
            if filas:
                salida.append({
                    "pagina": idx + 1, "trabajadores": filas,
                    "rotacion": int(orientacion),
                    "tamano_imagen_px": [int(im.width), int(im.height)],
                })
    return salida
