"""Lector independiente de certificados F30-1 digitales o escaneados.

No confirma autenticidad ante la DT ni pago si falta la página de resumen.
Agrupa por folio, valida RUT con módulo 11 y reintenta OCR cuando faltan filas.
"""
from __future__ import annotations

from collections import defaultdict
import re
import unicodedata
import fitz

MESES = {nombre: i for i, nombre in enumerate(
    ['enero', 'febrero', 'marzo', 'abril', 'mayo', 'junio',
     'julio', 'agosto', 'septiembre', 'octubre', 'noviembre', 'diciembre'], 1)}
MESES['setiembre'] = 9
RUT_RE = re.compile(r'(?<!\d)\d{1,2}[.,]?\s*\d{3}[.,]?\s*\d{3}\s*[-–]\s*[0-9Kk](?!\d)')
FOLIO_RE = re.compile(r'\b2000\s*[/|\\]\s*(20\d{2})\s*[/|\\]\s*(\d{7,9})\b')
MES_RE = re.compile(r'\b(' + '|'.join(MESES) + r')\s+(20\d{2})\b', re.I)
FILA_RE = re.compile(r'^\s*(?:\d{1,3}[.)]?\s+)?(' + RUT_RE.pattern + r')\s+(.{5,90})$', re.I)


def sin_acentos(texto: str) -> str:
    return ''.join(
        char for char in unicodedata.normalize('NFKD', texto)
        if not unicodedata.combining(char)
    )


def rut_valido(valor: str) -> str:
    rut = re.sub(r'[^0-9Kk]', '', valor).upper()
    if len(rut) not in (8, 9) or not rut[:-1].isdigit():
        return ''
    suma = sum(int(d) * (2 + i % 6) for i, d in enumerate(rut[-2::-1]))
    dig = 11 - suma % 11
    dv = '0' if dig == 11 else 'K' if dig == 10 else str(dig)
    return rut if rut[-1] == dv else ''


rut_normalizado = rut_valido


def _puntos_f301(texto: str) -> int:
    """Señales textuales reales, sin inventar un porcentaje de confianza OCR."""
    t = sin_acentos(texto).lower()
    palabras = (
        'certificado', 'cumplimiento', 'obligaciones laborales',
        'previsionales', 'nombre trabajador', 'trabajadores declarados',
        'detalle por periodo', 'cotizaciones previsionales',
    )
    return sum(bool(p in t) for p in palabras)


def _pagina_texto(pagina, psm=3) -> tuple[str, str]:
    """Extracción híbrida con orientación de respaldo para escaneos laterales.

    No rota PDFs digitales ni reinterpreta importes; usa orientación solo cuando
    Tesseract no identifica la estructura documental. Evita instalar OCR de pago.
    """
    texto = pagina.get_text('text', sort=True)
    if len(texto.strip()) > 180:
        return texto, 'DIGITAL'
    import pytesseract
    from PIL import Image

    pix = pagina.get_pixmap(
        matrix=fitz.Matrix(2.3, 2.3), colorspace=fitz.csRGB, alpha=False
    )
    img = Image.frombytes('RGB', (pix.width, pix.height), pix.samples)
    texto = pytesseract.image_to_string(
        img, lang='eng', config=f'--psm {psm}', timeout=18
    )
    if len(texto.strip()) < 100:
        alterno = pytesseract.image_to_string(
            img, lang='eng', config='--psm 6', timeout=18
        )
        if (_puntos_f301(alterno), len(alterno)) > (_puntos_f301(texto), len(texto)):
            texto = alterno
    if _puntos_f301(texto) < 2:
        # Buscar orientación solo en páginas con estructura OCR no recuperada.
        # OSD puede fallar en páginas con muy pocas letras.
        try:
            datos = pytesseract.image_to_osd(
                img, output_type=pytesseract.Output.DICT, timeout=7
            )
            rotacion = int(datos.get('rotate', 0))
        except Exception:
            rotacion = 0
        # Una orientación OSD válida suele ahorrar 2 pasadas adicionales;
        # si no existe, intentar ambos giros laterales y luego 180 grados.
        candidatos = (
            [rotacion] + [a for a in (90, 270, 180) if a != rotacion]
            if rotacion in (90, 180, 270) else [90, 270, 180]
        )
        mejor = (_puntos_f301(texto), len(texto))
        for angulo in candidatos:
            try:
                candidato = pytesseract.image_to_string(
                    img.rotate(-angulo, expand=True),
                    lang='eng', config='--psm 6', timeout=16
                )
            except Exception:
                continue
            puntuacion = (_puntos_f301(candidato), len(candidato))
            if puntuacion > mejor:
                texto, mejor = candidato, puntuacion
            if mejor[0] >= 3:
                break
    return texto, 'OCR'


def _nomina_en_texto(texto: str) -> tuple[list[dict], int | None, str]:
    limpio = sin_acentos(texto)
    if not re.search(
        r'Trabajadores\s+declarados|Detalle\s+por\s+Periodo|Nombre\s+Trabajador',
        limpio, re.I
    ):
        return [], None, ''
    total = re.search(
        r'Total\s+Trabajadores\s*[:.]?\s*(\d{1,4})', limpio, re.I
    )
    esperados = int(total.group(1)) if total else None
    idx = limpio.lower().find('detalle por periodo')
    periodo_match = MES_RE.search(limpio[idx:] if idx >= 0 else limpio)
    periodo = (
        f'{periodo_match.group(2)}-{MESES[periodo_match.group(1).lower()]:02d}'
        if periodo_match else ''
    )
    inicio = re.search(r'Nombre\s+Trabajador', limpio, re.I)
    bloque = texto[inicio.end():] if inicio else texto
    bloque = re.split(r'Total\s+Trabajadores', bloque, 1, flags=re.I)[0]
    nomina, vistos = [], set()
    for linea in bloque.splitlines():
        fila = FILA_RE.match(linea.strip())
        if not fila:
            continue
        rut = rut_valido(fila.group(1))
        nombre = re.sub(r'\s+', ' ', fila.group(2)).strip(' .:;|-')
        nombre = re.sub(r'\s+\d{1,2}$', '', nombre).strip()
        if rut and rut not in vistos and len(nombre.split()) >= 2:
            nomina.append({'trabajador_rut': rut, 'trabajador_nombre': nombre})
            vistos.add(rut)
    return nomina, esperados, periodo


def _nomina_relectura(pagina) -> tuple[list[dict], int | None, str]:
    """Reprocesar zona de nómina con contraste; sin fabricar dígitos."""
    import pytesseract
    from PIL import Image, ImageOps, ImageEnhance
    r = pagina.rect
    recorte = fitz.Rect(r.width*.09, r.height*.26, r.width*.89, r.height*.74)
    pix = pagina.get_pixmap(
        matrix=fitz.Matrix(3.2, 3.2), clip=recorte, alpha=False
    )
    img = Image.frombytes('RGB', (pix.width, pix.height), pix.samples)
    img = ImageEnhance.Contrast(ImageOps.grayscale(img)).enhance(1.6)
    opciones = []
    for modo in (6, 11):
        t = pytesseract.image_to_string(
            img, lang='eng', config=f'--psm {modo}', timeout=18
        )
        if 'detalle por periodo' not in sin_acentos(t).lower():
            t = 'Detalle por Periodo\n' + t
        opciones.append(_nomina_en_texto(t))
    return max(opciones, key=lambda x: (len(x[0]), bool(x[2])))


def _nomina_columnas(page, periodo, folio, archivo, numero_pagina, esperados=None):
    """Separar RUT y nombres utilizando las líneas de la tabla en escaneos."""
    try:
        import cv2
        import numpy as np
        import pytesseract
        from PIL import Image

        esc = 2
        pix = page.get_pixmap(
            matrix=fitz.Matrix(esc, esc), colorspace=fitz.csGRAY, alpha=False
        )
        gray = np.frombuffer(pix.samples, np.uint8).reshape(
            (pix.height, pix.width)
        )
        bw = cv2.adaptiveThreshold(
            gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
            cv2.THRESH_BINARY_INV, 31, 12
        )
        horizontal = cv2.morphologyEx(
            bw, cv2.MORPH_OPEN,
            cv2.getStructuringElement(
                cv2.MORPH_RECT, (max(90, int(gray.shape[1]*.16)), 1)
            )
        )
        contornos, _ = cv2.findContours(
            horizontal, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE
        )
        lineas = []
        for contorno in contornos:
            x, y, w, h = cv2.boundingRect(contorno)
            if w < gray.shape[1]*.15 or y/esc < 155 or y/esc > page.rect.height*.8:
                continue
            lineas.append((y/esc, x/esc, (x+w)/esc))
        grupos = []
        for y, x1, x2 in sorted(lineas):
            if not grupos or abs(y-grupos[-1]['y']) > 2.5:
                grupos.append({'y': y, 'l': x1, 'r': x2})
            else:
                grupos[-1]['l'] = min(grupos[-1]['l'], x1)
                grupos[-1]['r'] = max(grupos[-1]['r'], x2)
        runs, run = [], []
        for item in grupos:
            if run and not 9 <= item['y']-run[-1]['y'] <= 30:
                if len(run) >= 5:
                    runs.append(run)
                run = []
            run.append(item)
        if len(run) >= 5:
            runs.append(run)
        if not runs:
            return []
        runs.sort(key=lambda x: (abs(len(x)-int(esperados or 5)-4), -len(x)))
        lines = runs[0]
        if len(lines) < 6:
            return []
        starts = lines[2:-1]
        if esperados and len(starts) >= esperados+1:
            starts = starts[:esperados]
        if not starts:
            return []
        izq = min(x['l'] for x in lines)
        der = max(x['r'] for x in lines)
        ancho = der-izq
        if not 230 <= ancho <= page.rect.width:
            return []
        top = starts[0]['y']-3.5
        bottom = lines[min(2+len(starts), len(lines)-1)]['y']+2
        if bottom-top < 12:
            return []

        def columna(a, b):
            zona = fitz.Rect(a, top, b, bottom) & page.rect
            if zona.is_empty:
                return ''
            imagen = page.get_pixmap(
                matrix=fitz.Matrix(4, 4), clip=zona, alpha=False
            )
            im = Image.frombytes(
                'RGB', (imagen.width, imagen.height), imagen.samples
            )
            return pytesseract.image_to_string(
                im, lang='eng', config='--psm 6', timeout=12
            )

        texto_rut = columna(izq+ancho*.095, izq+ancho*.267)
        texto_nombre = columna(izq+ancho*.318, izq+ancho*.80)
        ruts = []
        for linea in texto_rut.splitlines():
            m = RUT_RE.search(linea.replace(',', '.'))
            if m:
                rut = rut_valido(m.group())
                if rut:
                    ruts.append(rut)
        nombres = []
        for linea in texto_nombre.splitlines():
            nombre = re.sub(
                r'[^\w\sÁÉÍÓÚÑáéíóúñ-]', ' ', linea
            ).strip(' -_')
            nombre = re.sub(r'\s+', ' ', nombre)
            if (len(nombre) >= 10 and len(nombre.split()) >= 2
                    and not re.search(
                        r'^(Total|Nombre|Trabajador)', nombre, re.I
                    )):
                nombres.append(nombre)
        if len(ruts) != len(nombres) or len(set(ruts)) != len(ruts):
            return []
        if esperados is not None and len(ruts) != esperados:
            return []
        return [
            {'trabajador_rut': rut, 'trabajador_nombre': nombre}
            for rut, nombre in zip(ruts, nombres)
        ]
    except Exception:
        return []


def _empresa(texto: str, subseccion: str, fin: str) -> tuple[str, str]:
    s = sin_acentos(texto)
    ini, limite = re.search(subseccion, s, re.I), re.search(fin, s, re.I)
    if not ini:
        return '', ''
    frag = s[ini.end():limite.start()
             if limite and limite.start() > ini.end() else ini.end()+1400]
    cabecera = re.search(r'Nombre\s+[o0]\s+Raz\w*\s+Social', frag, re.I)
    if not cabecera:
        return '', ''
    zona = re.split(
        r'\bRepresentante\s+Legal\b', frag[cabecera.end():],
        maxsplit=1, flags=re.I
    )[0]
    validos = [
        rut_valido(m.group()) for m in RUT_RE.finditer(zona)
        if rut_valido(m.group())
    ]
    if not validos:
        return '', ''
    nombre = re.sub(
        r'(?im)^\s*(?:RUT|Nombre\s+[o0]\s+Razon\s+Social)\s*$',
        '', zona
    )
    nombre = RUT_RE.sub(' ', nombre)
    nombre = re.sub(r'\bRUT\b\s*[.:,]?', ' ', nombre, flags=re.I)
    nombre = re.sub(r'\s+', ' ', nombre).strip(' :-_.—').upper()
    return (nombre, validos[0]) if len(nombre) >= 6 else ('', '')


def _periodo_resumen(texto: str) -> str:
    t = sin_acentos(texto)
    m = re.search(
        r'3\s*\.\s*1\s*[-.]?\s*Periodo\s*[:;]?\s*('
        + '|'.join(MESES) + r')\s+(20\d{2})', t, re.I
    )
    return f'{m.group(2)}-{MESES[m.group(1).lower()]:02d}' if m else ''


def _pago_resumen(texto: str) -> str:
    t = sin_acentos(texto)
    m = re.search(r'Cotizaciones\s+Previsionales', t, re.I)
    if not m:
        return 'NO_LEIBLE'
    tramo = t[m.end():m.end()+125]
    if (re.search(r'\b[Ss][Ii]\s+No\b', tramo)
            or re.search(r'Pagadas\s*\n\s*Si\b', tramo, re.I)):
        return 'SI_DECLARADO_EN_PDF'
    if (re.search(r'\bNo\s+Si\b', tramo, re.I)
            or re.search(r'Pagadas\s*\n\s*No\b', tramo, re.I)):
        return 'NO_DECLARADO_EN_PDF'
    return 'NO_LEIBLE'


def es_f301(data: bytes, nombre: str) -> bool:
    """Detecta incluso archivos mal nombrados por cabecera, no solo por '_F30'."""
    if re.search(r'(?i)(?:^|[_\s-])F30(?:[-_ ]?1)?(?:[_.( ]|$)', nombre):
        return True
    if not data.startswith(b'%PDF'):
        return False
    try:
        with fitz.open(stream=data, filetype='pdf') as pdf:
            if not len(pdf):
                return False
            texto, _ = _pagina_texto(pdf[0])
            s = sin_acentos(texto).lower()
            return ('certificado de cumplimiento' in s
                    and 'obligaciones laborales' in s)
    except Exception:
        return False


def analizar_f301(archivos: list[tuple[bytes, str]]):
    """Retorna certificados, nómina y alertas; jamás consulta el portal DT."""
    certificados, nomina_total, avisos = [], [], []
    for data, archivo in archivos:
        try:
            with fitz.open(stream=data, filetype='pdf') as pdf:
                if len(pdf) > 80:
                    raise ValueError('PDF muy extenso: dividir por certificados')
                grupos = defaultdict(list)
                ultimo_folio = ''
                for i, pagina in enumerate(pdf):
                    texto, origen = _pagina_texto(pagina)
                    match = FOLIO_RE.search(texto)
                    if match:
                        ultimo_folio = f'2000/{match.group(1)}/{match.group(2)}'
                    folio = ultimo_folio or f'SIN_FOLIO_PAG_{i+1}'
                    trabajadores, esperados, periodo = _nomina_en_texto(texto)
                    es_nomina = bool(re.search(
                        r'Trabajadores\s+declarados|Nombre\s+Trabajador',
                        sin_acentos(texto), re.I
                    ))
                    if es_nomina and (
                        not trabajadores or esperados is None
                        or len(trabajadores) < esperados
                    ):
                        otros, n, per = _nomina_relectura(pagina)
                        if len(otros) > len(trabajadores):
                            trabajadores = otros
                        esperados = esperados if esperados is not None else n
                        periodo = periodo or per
                    alterno = ''
                    if origen == 'OCR' and (
                        i == 0
                        or re.search(r'3\s*[-.]?\s*Periodos', texto, re.I)
                    ):
                        alterno, _ = _pagina_texto(pagina, psm=11)
                        if not match:
                            m2 = FOLIO_RE.search(alterno)
                            if m2:
                                folio = f'2000/{m2.group(1)}/{m2.group(2)}'
                                ultimo_folio = folio
                    if es_nomina and (
                        not trabajadores or esperados is None
                        or len(trabajadores) < esperados
                    ):
                        try:
                            from f301_nomina_reforzada import extraer_nomina_por_tokens
                            rescate, per = extraer_nomina_por_tokens(
                                pagina, periodo, folio, archivo, i+1, esperados
                            )
                            if len(rescate) > len(trabajadores):
                                trabajadores = [
                                    {'trabajador_rut': r['trabajador_rut'],
                                     'trabajador_nombre': r['trabajador_nombre']}
                                    for r in rescate
                                ]
                            periodo = periodo or per
                        except Exception:
                            pass
                    if es_nomina and (
                        not trabajadores or esperados is None
                        or len(trabajadores) < esperados
                    ):
                        rescate = _nomina_columnas(
                            pagina, periodo, folio, archivo, i+1, esperados
                        )
                        if len(rescate) > len(trabajadores):
                            trabajadores = rescate
                    grupos[folio].append({
                        'pagina': i+1, 'texto': texto, 'origen': origen,
                        'alterno': alterno, 'trabajadores': trabajadores,
                        'total': esperados, 'periodo': periodo,
                    })
                claves = list(grupos)
                # Una portada inicial sin folio no es otro certificado si el
                # primer folio real aparece en la página siguiente.
                if claves and claves[0].startswith('SIN_FOLIO') and len(claves) > 1:
                    valido = next(
                        (k for k in claves if not k.startswith('SIN_FOLIO')), ''
                    )
                    if valido:
                        grupos[valido] = grupos[claves[0]] + grupos[valido]
                        del grupos[claves[0]]
                for folio, paginas in grupos.items():
                    conjunto = '\n'.join(p['texto'] for p in paginas)
                    portada = next((
                        p['texto'] for p in paginas
                        if re.search(
                            r'1\s*\.\s*1\s*[-.]?\s*Antecedentes',
                            p['texto'], re.I
                        )
                    ), '')
                    empresa, rut = _empresa(
                        portada, r'1\s*\.\s*1\s*[-.]?\s*Antecedentes',
                        r'1\s*\.\s*2\s*[-.]?\s*Empresa'
                    )
                    if (not empresa or not rut) and portada:
                        alterno = next((
                            p['alterno'] for p in paginas
                            if p['alterno'] and '1.1' in p['alterno']
                        ), '')
                        e2, r2 = _empresa(
                            alterno, r'1\s*\.\s*1\s*[-.]?\s*Antecedentes',
                            r'1\s*\.\s*2\s*[-.]?\s*Empresa'
                        )
                        empresa, rut = e2 or empresa, r2 or rut
                    principal, rut_principal = _empresa(
                        portada, r'1\s*\.\s*2\s*[-.]?\s*Empresa',
                        r'2\s*[-.]?\s*Obra'
                    )
                    por_rut = {}
                    for p in paginas:
                        for trabajador in p['trabajadores']:
                            por_rut[trabajador['trabajador_rut']] = {
                                **trabajador, 'folio': folio,
                                'periodo': p['periodo'], 'pagina': p['pagina'],
                                'archivo': archivo,
                            }
                    valores = [
                        p['total'] for p in paginas
                        if p['total'] is not None
                    ]
                    esperados = max(valores) if valores else None
                    periodos = [p['periodo'] for p in paginas if p['periodo']]
                    periodo = _periodo_resumen(conjunto) or (
                        periodos[0] if periodos else ''
                    )
                    hay_resumen = bool(re.search(
                        r'3\s*\.\s*1\s*[-.]?\s*Periodo|3\s*[-.]?\s*Periodos',
                        conjunto, re.I
                    ))
                    resumen_ocr = '\n'.join(
                        p['alterno'] or p['texto'] for p in paginas
                        if 'Periodos' in sin_acentos(p['texto'])
                        or 'Periodo :' in sin_acentos(p['texto'])
                    )
                    cotizaciones = (
                        _pago_resumen(resumen_ocr)
                        if hay_resumen else 'SIN_RESUMEN_NO_SE_PUEDE_CONFIRMAR'
                    )
                    problemas = []
                    if not rut:
                        problemas.append('RUT del empleador no validado')
                    if not periodo:
                        problemas.append('Período no identificado')
                    if esperados is not None and len(por_rut) != esperados:
                        problemas.append(
                            f'Nómina incompleta: {len(por_rut)} de {esperados}'
                        )
                    if not hay_resumen:
                        problemas.append(
                            'Falta página de resumen: no se puede confirmar pago'
                        )
                    if not por_rut:
                        problemas.append('No se recuperaron RUT de nómina')
                    if folio.startswith('SIN_FOLIO'):
                        problemas.append('Folio no identificado')
                    certificados.append({
                        'archivo': archivo, 'folio': folio,
                        'contratista': empresa, 'rut_contratista': rut,
                        'empresa_principal': principal,
                        'rut_principal': rut_principal, 'periodo': periodo,
                        'trabajadores_declarados': esperados,
                        'trabajadores_identificados': len(por_rut),
                        'cotizaciones': cotizaciones,
                        'paginas': ', '.join(str(p['pagina']) for p in paginas),
                        'tipo_lectura': (
                            'OCR' if any(
                                p['origen'] == 'OCR' for p in paginas
                            ) else 'DIGITAL'
                        ),
                        'verificacion_dt': 'PENDIENTE_PORTAL_DT',
                        'observaciones': ' | '.join(problemas),
                    })
                    nomina_total.extend(por_rut.values())
                    avisos.extend([
                        {'archivo': archivo, 'folio': folio, 'detalle': problema}
                        for problema in problemas
                    ])
        except Exception as exc:
            avisos.append({
                'archivo': archivo, 'folio': '',
                'detalle': f'No se pudo procesar PDF: {type(exc).__name__}'
            })
    return certificados, nomina_total, avisos
