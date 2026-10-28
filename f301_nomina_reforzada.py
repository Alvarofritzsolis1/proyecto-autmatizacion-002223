"""Rescate de filas F30-1 escaneadas mediante coordenadas OCR (sin inventar RUT)."""
from __future__ import annotations

import re
import unicodedata
import fitz
import pandas as pd

from f301_lector import rut_normalizado, MESES

RUT_PATRON = re.compile(r'(?<!\d)\d{1,2}[., ]?\d{3}[., ]?\d{3}\s*[-–]\s*[0-9Kk](?!\d)')


def _ocr_tokens(page):
    from PIL import Image
    import pytesseract

    pix = page.get_pixmap(
        matrix=fitz.Matrix(2.5, 2.5), colorspace=fitz.csGRAY, alpha=False
    )
    img = Image.frombytes('L', (pix.width, pix.height), pix.samples)
    df = pytesseract.image_to_data(
        img, lang='eng', config='--oem 1 --psm 11',
        output_type=pytesseract.Output.DATAFRAME, timeout=18
    )
    tokens = []
    for _, row in df.iterrows():
        text = row.get('text')
        if pd.isna(text) or not str(text).strip():
            continue
        tokens.append({
            't': str(text).strip(),
            'x': int(row['left']), 'y': int(row['top']),
            'w': int(row['width']), 'h': int(row['height'])
        })
    return tokens, pix.width, pix.height


def extraer_nomina_por_tokens(
    page, periodo: str, folio: str, archivo: str, pagina: int, esperados=None
):
    tokens, w, h = _ocr_tokens(page)
    etiquetas_nombre = [
        x for x in tokens
        if x['t'].lower().startswith('nombre') and .16*h < x['y'] < .60*h
    ]
    etiquetas_rut = [
        x for x in tokens
        if x['t'].upper().strip('.,:') == 'RUT' and .16*h < x['y'] < .60*h
    ]
    if not etiquetas_nombre or not etiquetas_rut:
        return [], ''
    titulo_nombre = max(etiquetas_nombre, key=lambda x: x['y'])
    titulo_rut = min(etiquetas_rut, key=lambda x: abs(x['y'] - titulo_nombre['y']))
    if abs(titulo_rut['y'] - titulo_nombre['y']) > 35:
        return [], ''
    y_cabecera = max(titulo_rut['y'], titulo_nombre['y'])
    y_final = min(h*.78, y_cabecera + max(250, ((esperados or 7)+2)*60))
    totales = [
        x for x in tokens
        if x['t'].lower() == 'total'
        and y_cabecera < x['y'] < y_final
        and x['x'] > titulo_nombre['x']
    ]
    if totales:
        y_final = min(y_final, min(x['y'] for x in totales))
    ruts = []
    for token in tokens:
        if not (y_cabecera+12 <= token['y'] < y_final):
            continue
        if not (titulo_rut['x']-30 <= token['x'] < titulo_nombre['x']-20):
            continue
        match = RUT_PATRON.search(token['t'].replace(',', '.'))
        if not match:
            continue
        rut = rut_normalizado(match.group())
        if rut:
            ruts.append((token, rut))
    ruts.sort(key=lambda item: item[0]['y'])
    if not ruts or len({rut for _, rut in ruts}) != len(ruts):
        return [], ''
    nomina = []
    for token, rut in ruts:
        words = [
            x for x in tokens
            if titulo_nombre['x']-6 <= x['x'] < w*.87
            and abs(x['y']-token['y']) <= 21
            and re.fullmatch(r'[A-Za-zÁÉÍÓÚÑÜáéíóúñü]+', x['t'])
        ]
        words.sort(key=lambda x: x['x'])
        nombre = ' '.join(x['t'] for x in words).strip()
        if len(nombre.split()) < 2:
            return [], ''
        nomina.append({
            'trabajador_rut': rut, 'trabajador_nombre': nombre,
            'folio': folio, 'periodo': periodo,
            'archivo': archivo, 'pagina': pagina,
        })
    if esperados is not None and len(nomina) != esperados:
        return [], ''
    periodo_detectado = ''
    for token in tokens:
        mes = unicodedata.normalize('NFKD', token['t'].lower())
        mes = ''.join(c for c in mes if not unicodedata.combining(c)).strip(' .,:')
        if mes not in MESES or not (.15*h < token['y'] < y_cabecera):
            continue
        anyos = [
            x for x in tokens
            if re.fullmatch(r'20\d{2}', x['t'])
            and abs(x['y'] - token['y']) < 25
            and 0 < x['x'] - token['x'] < 170
        ]
        if len(anyos) == 1:
            periodo_detectado = f"{anyos[0]['t']}-{MESES[mes]:02d}"
            break
    if periodo_detectado and not periodo:
        for trabajador in nomina:
            trabajador['periodo'] = periodo_detectado
    return nomina, periodo_detectado
