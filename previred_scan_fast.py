"""OCR rápido y verificable para PDFs PREVIRED ESCANEADOS con tablas rectangulares.

Diseño: identificar retículas sin OCR -> extraer únicamente columnas RUT, días,
base imponible y nombre de detalle -> OCR por lotes -> validar DV y cuadratura.
No OCR a portadas, firmas, descripciones, cotizaciones pagadas ni totales sueltos.
Se acepta el resultado solo si el PDF coincide con los perfiles geométricos
reconocidos; los datos dudosos quedan en revisión y no se inventan.
"""
from __future__ import annotations

import io
import re
import time
from collections import defaultdict
from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd
from PIL import Image, ImageOps

from previred_pdf import _rut_clean, _rut_ok

# Cantidad de límites verticales de los cuatro formularios PREVIRED escaneados.
# No corresponde a cantidad de trabajadores ni a porcentaje de cotizaciones.
RETICULAS = {10: "mutual", 14: "seguro_social", 16: "afp", 17: "salud"}
RUT_EN_TEXTO = re.compile(r"\d{1,2}[. ]?\d{3}[. ]?\d{3}[- ]?[0-9K]", re.I)
NUMERO = re.compile(r"\d{1,3}(?:\.\d{3})+|\d+", re.I)


@dataclass
class Plantilla:
    tipo: str
    numero_pagina: int
    foto: Image.Image
    limites_x: list[int]
    filas_y: list[tuple[int, int]]


def _grupos(ids: np.ndarray) -> list[list[int]]:
    grupos: list[list[int]] = []
    for item in ids:
        v = int(item)
        if not grupos or v > grupos[-1][-1] + 1:
            grupos.append([v])
        else:
            grupos[-1].append(v)
    return grupos


def _lineas_horizontales(gris: np.ndarray) -> list[int]:
    h, w = gris.shape
    x1, x2 = round(.062*w), round(.936*w)
    cuenta = (gris[:, x1:x2] < 158).sum(axis=1)
    idx = np.flatnonzero((cuenta > (x2-x1)*.76) & (np.arange(h) < .69*h) & (np.arange(h) > .12*h))
    return [int(np.median(g)) for g in _grupos(idx)]


def _runs_repetidos(ys: list[int], h: int) -> list[int]:
    # Elegir el paso más frecuente de las filas, no confundir una fila de
    # TOTAL (18-25 px) con movimientos (13-16 px en esta plantilla).
    if len(ys) < 3:
        return []
    runs = []
    for paso in range(max(8,int(h*.010)),min(22,int(h*.021)) + 1):
        for i in range(len(ys)-1):
            r=[ys[i]]
            for j in range(i+1,len(ys)):
                if abs((ys[j]-ys[j-1])-paso) <= 1.7:
                    r.append(ys[j])
                else:
                    break
            if len(r)>=3:
                runs.append(r)
    return max(runs,key=lambda g:(len(g),-g[0]),default=[])


def _lineas_verticales(gris: np.ndarray, run: list[int], incluir_cabecera: bool = False) -> list[int]:
    h,w=gris.shape
    if not run:
        return []
    paso=int(np.median(np.diff(run)))
    y1=run[0]-paso+2 if incluir_cabecera else run[0]+2
    y2=min(h,run[-1]-1)
    if y2-y1<20:
        return []
    # Diferenciar borde continuo de letras que aparecen en la misma columna:
    # un borde vertical recorre TODAS las filas consecutivamente.
    mascara=gris[y1:y2,:]<180
    actual=np.zeros(w,dtype=np.int32)
    maxima=np.zeros(w,dtype=np.int32)
    for linea in mascara:
        actual=np.where(linea,actual+1,0)
        maxima=np.maximum(maxima,actual)
    indices=np.flatnonzero((maxima>(y2-y1)*.65)&(np.arange(w)>.045*w)&(np.arange(w)<.96*w))
    return [int(np.median(g)) for g in _grupos(indices)]


def _preparar(imagen: Image.Image, pagina: int) -> Plantilla|None:
    g=np.array(imagen.convert('L'))
    h,w=g.shape
    if w < h:
        return None
    run = _runs_repetidos(_lineas_horizontales(g),h)
    if not run:
        return None
    verticales = _lineas_verticales(g,run)
    tipo = RETICULAS.get(len(verticales))
    if not tipo:
        verticales = _lineas_verticales(g,run,incluir_cabecera=True)
        tipo = RETICULAS.get(len(verticales))
    if not tipo:
        return None
    step = int(round(np.median(np.diff(run))))
    if not 10 <= step <= h*.04:
        return None
    if tipo=='afp':
        # La primera fila AFP se encuentra ANTES de la primera regla larga,
        # porque la cabecera fusionada no termina en línea horizontal completa.
        run=[run[0]-step]+run
    elif tipo=='seguro_social':
        # En este formulario, la última fila precede a un total fusionado;
        # su separador puede no atravesar todas las columnas.
        run=run + [run[-1]+step]
    filas=[(a,b) for a,b in zip(run[:-1],run[1:]) if b-a>=8]
    if len(filas)>250:
        return None
    return Plantilla(tipo,pagina,imagen,verticales,filas)


def _extraer_plantillas(contenido: bytes) -> list[Plantilla]:
    import fitz
    doc=fitz.open(stream=contenido,filetype='pdf')
    if doc.page_count>120:
        raise ValueError('El PDF supera el límite de 120 páginas de OCR en línea; divídelo para proteger la memoria.')
    perfiles=[]
    for i,page in enumerate(doc):
        # Páginas digitales deben pasar al lector de texto especializado; el OCR es el fallback.
        if len(page.get_text().strip()) > 120:
            return []
        # Render a ~1.8x; suficiente para texto escaneado sin agotar CPU.
        pix=page.get_pixmap(matrix=fitz.Matrix(1.8,1.8),colorspace=fitz.csGRAY,alpha=False)
        im=Image.frombytes('L',(pix.width,pix.height),pix.samples)
        # Si el PDF está guardado de lado se identifican las reglas tras girarlo.
        candidatas=[im]
        if im.height>im.width:
            candidatas=[im.transpose(Image.Transpose.ROTATE_270),im.transpose(Image.Transpose.ROTATE_90)]
        hallado=None
        for candidata in candidatas:
            hallado=_preparar(candidata,i+1)
            if hallado:
                break
        if hallado:
            perfiles.append(hallado)
    return perfiles


def _roi(plantilla:Plantilla, columna:str, fila:int) -> Image.Image|None:
    x=plantilla.limites_x
    y1,y2=plantilla.filas_y[fila]
    tipo=plantilla.tipo
    cols={
        'salud': {'rut':(1,2),'nombre':(2,5),'dias':(5,6),'renta':(7,8)},
        'seguro_social': {'rut':(1,2),'nombre':(2,3),'dias':(9,10),'renta':(3,4)},
        'mutual': {'rut':(0,1),'nombre':(1,4),'renta':(4,5)},
        'afp': {'rut':(0,1),'nombre':(1,2),'renta':(2,3)},
    }
    if columna not in cols[tipo]:
        return None
    left,right=cols[tipo][columna]
    if right>=len(x):
        return None
    a,b=x[left]+2,x[right]-2
    if b-a<8 or y2-y1<8:
        return None
    return plantilla.foto.crop((a,y1+2,b,y2-1))


def _montar_celdas(plantilla:Plantilla, columnas:list[str]) -> tuple[Image.Image,list[tuple[int,int]]]:
    """Concatenar solo datos esenciales: una llamada a Tesseract por página.

    El texto está posicionado en columnas sintéticas con coordenadas conocidas.
    Se elimina la retícula y se triplica la resolución de cada recorte pequeño.
    """
    amplitudes={'rut':240,'dias':96,'renta':192,'nombre':680}
    offset=0
    posiciones=[]
    for col in columnas:
        posiciones.append((offset,offset+amplitudes[col]));offset+=amplitudes[col]+24
    imagen=Image.new('L',(offset+18,len(plantilla.filas_y)*56+8),255)
    for fila in range(len(plantilla.filas_y)):
        for col,(left,right) in zip(columnas,posiciones):
            celda=_roi(plantilla,col,fila)
            if celda is None:
                continue
            maxw=right-left-12
            # Para RUT, renta, días, el objetivo es tamaño de letra ~23-30 px.
            escala=3.0 if col!='nombre' else 2.4
            ww=min(int(celda.width*escala),maxw)
            hh=min(int(celda.height*escala),44)
            if ww<3 or hh<3:
                continue
            celda=ImageOps.autocontrast(celda.resize((ww,hh),Image.Resampling.BICUBIC))
            celda=celda.point(lambda v: 0 if v < 166 else 255)
            imagen.paste(celda,(left+6,fila*56+6))
    return imagen,posiciones


def _ocr_lote(plantilla:Plantilla,columnas:list[str]) -> tuple[list[dict[str,str]], list[str]]:
    import pytesseract
    imagen,posiciones=_montar_celdas(plantilla,columnas)
    # Texto solo: una llamada a Tesseract por página. PSM 6 evita el modo de
    # detección global de documentos que es lento para tablas de muchas filas.
    df=pytesseract.image_to_data(
        imagen,lang='eng',config='--oem 1 --psm 6',
        output_type=pytesseract.Output.DATAFRAME,
    )
    datos=[defaultdict(str) for _ in plantilla.filas_y]
    for _,p in df.iterrows():
        if pd.isna(p.get('text')) or float(p.get('conf',-1))<12:
            continue
        t=str(p['text']).strip()
        if not t:
            continue
        fila=int((float(p['top'])+float(p['height'])/2)//56)
        if not 0<=fila<len(datos):
            continue
        xc=float(p['left'])+float(p['width'])/2
        for col,(x1,x2) in zip(columnas,posiciones):
            if x1<=xc<x2:
                datos[fila][col]+=(' ' if datos[fila][col] else '')+t
                break
    return [dict(d) for d in datos],[]


def _ocr_columna_digitos(plantilla:Plantilla) -> list[dict[str,str]]:
    """Tesseract con diccionario de dígitos: más rápido y preciso que OCR general.

    Verificar RUT con DV, y bases entre instituciones, antes de usar la cifra.
    """
    import pytesseract
    cols=['rut']+(['dias'] if plantilla.tipo in ('salud','seguro_social') else [])+['renta']
    imagen,posiciones=_montar_celdas(plantilla,cols)
    df=pytesseract.image_to_data(imagen,lang='eng',config='--oem 1 --psm 6 -c tessedit_char_whitelist=0123456789.-K',output_type=pytesseract.Output.DATAFRAME)
    datos=[defaultdict(str) for _ in plantilla.filas_y]
    for _,p in df.iterrows():
        if pd.isna(p.get('text')):
            continue
        t=str(p['text']).strip()
        if not t:
            continue
        fila=int((float(p['top'])+float(p['height'])/2)//56)
        if not 0<=fila<len(datos):
            continue
        xc=float(p['left'])+float(p['width'])/2
        for col,(a,b) in zip(cols,posiciones):
            if a<=xc<b:
                datos[fila][col]+=(' ' if datos[fila][col] else '')+t
                break
    return [dict(x) for x in datos]


def _ocr_celda(plantilla: Plantilla, columna: str, fila: int, solo_digitos: bool = True) -> str:
    """Reintento preciso SOLO si el lote OCR da datos dudosos."""
    import pytesseract
    c=_roi(plantilla,columna,fila)
    if c is None:
        return ''
    # Alejar bordes de celdas y ampliar el texto pequeño.
    c=ImageOps.autocontrast(c.resize((c.width*4,c.height*4),Image.Resampling.BICUBIC))
    conf='--oem 1 --psm 7'
    if solo_digitos:
        conf+=' -c tessedit_char_whitelist=0123456789.-K'
    return pytesseract.image_to_string(c,lang='eng',config=conf).strip()


def _nombre_salud(plantilla: Plantilla, fila: int) -> str:
    # Tesseract PSM7 funciona especialmente bien con una línea de nombre.
    # OCR con ampliación moderada: ampliar demasiado puede borrar letras finas.
    import pytesseract
    celda=_roi(plantilla,'nombre',fila)
    if celda is None:return ''
    celda=ImageOps.autocontrast(celda.resize((celda.width*2,celda.height*2),Image.Resampling.BICUBIC))
    txt=pytesseract.image_to_string(celda,lang='eng',config='--oem 1 --psm 7')
    txt=re.sub(r'[^A-ZÁÉÍÓÚÑÜa-záéíóúüñ ]',' ',txt)
    return ' '.join(txt.upper().split())


def _rut(texto: str) -> str:
    v=_rut_clean(texto)
    if _rut_ok(v):
        return v
    # OCR puede insertar barras, corchetes y espacios; nunca alterar dígitos
    # arbitrariamente para forzar un DV. El cruce posterior hará la revisión.
    return ''


def _renta(texto: str) -> int|None:
    t=re.sub(r'[^\d.]','',texto)
    if not t:
        return None
    if re.fullmatch(r'\d{1,3}(?:\.\d{3})+|\d+',t):
        n=int(t.replace('.',''))
        return n if n>=0 else None
    return None


def _ocr_num_con_escala(plantilla: Plantilla, columna: str, fila: int, escala: float = 2.0) -> int|None:
    import pytesseract
    recorte=_roi(plantilla,columna,fila)
    if recorte is None:
        return None
    recorte=ImageOps.autocontrast(recorte.resize((int(recorte.width*escala),int(recorte.height*escala)),Image.Resampling.BICUBIC))
    txt=pytesseract.image_to_string(recorte,lang='eng',config='--oem 1 --psm 7 -c tessedit_char_whitelist=0123456789.')
    return _renta(txt)


def _seleccionar_valor(candidatos: list[int|None], esperado: int|None) -> tuple[int|None,bool]:
    """Nunca usar el valor de otra institución como sustituto de un OCR ausente.

    Solo elegir un importe que *aparece* en esta misma celda. Si hay lecturas
    contradictorias, el cruce permite decidir entre candidatos observados,
    dejando constancia de revisión.
    """
    valores=[v for v in candidatos if v is not None]
    if not valores:
        return None,True
    conteo={v:valores.count(v) for v in set(valores)}
    elegido=max(conteo,key=lambda n:(conteo[n],n==esperado))
    if esperado is not None and esperado in conteo and conteo[esperado]>=1:
        elegido=esperado
    return elegido,len(conteo)>1


def _contexto(documento: bytes, plantillas:list[Plantilla]) -> tuple[str,str,str,str]:
    """Lee solamente zonas de cabecera en lugar de las portadas completas."""
    import pytesseract
    salud=next((p for p in plantillas if p.tipo=='salud'),None)
    uno=salud or plantillas[0]
    w,h=uno.foto.size
    if salud:
        # Bajo el rótulo 'ANEXOS DE DETALLE': razón social y RUT del empleador.
        imagen=uno.foto.crop((int(.16*w),int(.169*h),int(.51*w),int(.24*h)))
        texto=pytesseract.image_to_string(imagen.resize((imagen.width*2,imagen.height*2)),lang='eng',config='--psm 6')
        lineas=[l.strip() for l in texto.splitlines() if len(l.strip())>3]
        nombre=next((re.sub(r'^\s*(?:RE\s+)?','',l,flags=re.I).strip(' ._-') for l in lineas if len(l)>12 and not RUT_EN_TEXTO.search(l) and len(l.split())>=2), '')
        rut_match=RUT_EN_TEXTO.search(texto)
        empleador_rut=_rut(rut_match.group()) if rut_match else ''
        if not empleador_rut:
            cr=uno.foto.crop((int(.175*w),int(.193*h),int(.50*w),int(.23*h)))
            extra=pytesseract.image_to_string(cr.resize((cr.width*2,cr.height*2)),lang='eng',config='--psm 6')
            rut_match=RUT_EN_TEXTO.search(extra)
            empleador_rut=_rut(rut_match.group()) if rut_match else ''
    else:
        nombre='';empleador_rut=''
    # El período legal pertenece a remuneraciones, NO al mes del nombre del PDF.
    # Leer encabezado de página de detalle mutual/AFP/Seguro Social.
    cab=next((p for p in plantillas if p.tipo in ('mutual','afp','seguro_social')),uno)
    w,h=cab.foto.size
    crop=cab.foto.crop((int(.52*w),int(.05*h),int(.72*w),int(.10*h)))
    ts=pytesseract.image_to_string(crop.resize((crop.width*2,crop.height*2)),lang='eng',config='--psm 6')
    m=re.search(r'(0?[1-9]|1[0-2])\s*[/.-]\s*(20\d{2})',ts)
    if m:
        periodo=f'{m.group(2)}-{int(m.group(1)):02d}'
    elif salud:
        cr=salud.foto.crop((int(.8*w),int(.19*h),int(.95*w),int(.24*h)))
        ts=pytesseract.image_to_string(cr.resize((cr.width*2,cr.height*2)),lang='eng',config='--psm 6')
        m=re.search(r'(0?[1-9]|1[0-2])\s+20(\d{2})',ts)
        periodo=f'20{m.group(2)}-{int(m.group(1)):02d}' if m else ''
    else: periodo=''
    return nombre.upper(),empleador_rut,periodo,'ACHS' if any(p.tipo=='mutual' for p in plantillas) else ''


def _advertencias_ocr_por_trabajador(invalidas, fuentes_rut):
    """Asigna al RUT lecturas OCR de sus propias filas.

    Si una fila perdió RUT o renta por completo, no se sabe a quién asignarla:
    se conserva como problema del documento para evitar falsos conformes.
    """
    referencias = {
        (pagina, fila + 1)
        for movimientos in fuentes_rut.values()
        for pagina, fila, _, _ in movimientos
    }
    resultado = []
    for mensaje in invalidas:
        m = re.match(r'^p\.(\d+), fila (\d+): (.*)
    """Extractor opcional para PREVIRED escaneado, no sustituye lectura digital.

    Devuelve None si el documento no coincide con el perfil de tablas; entonces
    entra el procesador estándar. Nunca emite 'CONFORME' sin respaldo total.
    """
    perfiles=_extraer_plantillas(contenido)
    tipos={p.tipo for p in perfiles}
    if not perfiles or len(tipos)<2 or 'salud' not in tipos:
        return None
    nombres_empleador,rut_empleador,periodo,mutual=_contexto(contenido,perfiles)
    datos:dict[str,dict[str,list[tuple[int,int,int|None,int|None]]]]=defaultdict(lambda:defaultdict(list))
    nombres: dict[str,str] = {}
    invalidas: list[str] = []
    salud_por_posicion: list[tuple[str,int|None,int|None]] = []
    # Primero Fonasa: su RUT y días sirven como control independiente de otras
    # instituciones, sin imponer su base como la base de AFP o Mutual.
    orden=sorted(perfiles,key=lambda p:0 if p.tipo=='salud' else 1)
    for p in orden:
        lote=_ocr_columna_digitos(p)
        nfilas=len(p.filas_y)
        # Una fuente con igual orden y número de filas puede utilizarse para
        # reconocer un RUT ilegible, pero solo si tres RUT válidos anclan el orden.
        puede_alinear=False
        if p.tipo in ('mutual','seguro_social') and len(salud_por_posicion)==nfilas:
            anclas=[(j,_rut(v.get('rut',''))) for j,v in enumerate(lote) if _rut(v.get('rut',''))]
            correctas=sum(1 for j,r in anclas if r==salud_por_posicion[j][0])
            puede_alinear=(correctas>=3 and correctas==len(anclas))
        for j,v in enumerate(lote):
            # La cabecera o el total no son trabajadores: evita OCR adicional.
            if not v.get('rut') and not v.get('renta') and not v.get('dias'):
                if p.tipo=='salud':
                    salud_por_posicion.append(('',None,None))
                continue
            rut=_rut(v.get('rut',''))
            if not rut:
                rut=_rut(_ocr_celda(p,'rut',j))
            if not rut and puede_alinear:
                rut=salud_por_posicion[j][0]
                if rut:
                    invalidas.append(f'p.{p.numero_pagina}, fila {j+1}: RUT alineado con Salud; cotejar visualmente')
            # En salud se puede corroborar por RUT; en las otras instituciones,
            # el esperado sirve únicamente para resolver discrepancias entre
            # montos *leídos realmente* en el propio recorte de esa fuente.
            esperado=None
            if p.tipo!='salud':
                val_salud=datos.get(rut,{}).get('salud',[])
                if val_salud:esperado=sum(row[2] for row in val_salud)
            cifra_lote=_renta(v.get('renta',''))
            # Una cifra coincidente en el OCR y en la fuente independiente
            # NO necesita otra invocación por celda; ahorro clave en nóminas grandes.
            if esperado is not None and cifra_lote==esperado:
                candidatos=[cifra_lote]
            else:
                cifra_2x=_ocr_num_con_escala(p,'renta',j,2.0)
                candidatos=[cifra_lote,cifra_2x]
                if (cifra_lote is None or cifra_2x is None or cifra_lote!=cifra_2x) and (esperado is None or esperado not in candidatos):
                    candidatos.append(_ocr_num_con_escala(p,'renta',j,3.0))
            renta,contradiccion=_seleccionar_valor(candidatos,esperado)
            if contradiccion:
                invalidas.append(f'p.{p.numero_pagina}, fila {j+1}: lecturas alternativas de renta {sorted(set(n for n in candidatos if n is not None))}; cotejar')
            dias=None
            if p.tipo=='salud':
                dias=_ocr_num_con_escala(p,'dias',j,2.0)
                # Para 11 días, a veces el OCR reconoce únicamente '1'.
                # Un segundo recorte independiente verifica los dos caracteres.
                if dias is None or dias==1:
                    alt=_ocr_num_con_escala(p,'dias',j,4.0)
                    if alt is not None and 0<=alt<=31:
                        dias=alt
                if dias is None:
                    dias=_renta(v.get('dias',''))
                if dias is None or dias>31:
                    invalidas.append(f'p.{p.numero_pagina}, fila {j+1}: días Salud no verificados')
                    dias=None
            elif p.tipo=='seguro_social':
                dias=_ocr_num_con_escala(p,'dias',j,1.5)
                # Las tablas muy pequeñas pueden confundir 6 con 5/8 y 11 con
                # 41; cotejar contra salud si se reconoce alternativamente.
                if dias is None or dias>31:
                    dias=_renta(v.get('dias',''))
                if dias is not None and dias>31:
                    dias=None
                ds=datos.get(rut,{}).get('salud',[])
                dia_esperado=sum(x[3] for x in ds if x[3] is not None) if ds else None
                if dia_esperado is not None and dias != dia_esperado:
                    # Segundo intento, sin copiar días de Salud a Seguro Social.
                    alternativas=[_ocr_num_con_escala(p,'dias',j,escala) for escala in (1.4,2.5,3.2)]
                    if dia_esperado in alternativas:
                        dias=dia_esperado  # leído en el SS por un segundo OCR
                    else:
                        # No copiar días de Salud a Seguro Social: se registra
                        # discrepancia para revisión humana.
                        invalidas.append(f'p.{p.numero_pagina}, fila {j+1}: días Seguro Social no concuerdan con Salud')
            if p.tipo=='salud':
                salud_por_posicion.append((rut,renta,dias))
            if not rut:
                if re.search(r'\d{5,}',v.get('rut','')):
                    invalidas.append(f'p.{p.numero_pagina}, fila {j+1}: RUT no reconocido')
                continue
            if renta is None:
                invalidas.append(f'p.{p.numero_pagina}, fila {j+1}: base imponible no reconocida')
                continue
            if dias is not None and not 0<=dias<=31:
                dias=None
            datos[rut][p.tipo].append((p.numero_pagina,j,renta,dias))
            if p.tipo=='salud':
                nombre=_nombre_salud(p,j)
                if nombre:nombres[rut]=nombre
    if not datos:
        raise ValueError('OCR escaneado detectó las tablas, pero no extrajo RUT y rentas verificables.')
    # Comprobar coherencia de todas las fuentes, incluidos registros omitidos.
    fuentes={t for t in tipos if t in ('salud','afp','mutual','seguro_social')}
    totales={t:sum(row[2] for por in datos.values() for row in por.get(t,[])) for t in fuentes}
    tam_fuentes={t:len({rut for rut,por in datos.items() if por.get(t)}) for t in fuentes}
    ruts_salud={rut for rut,fu in datos.items() if fu.get('salud')}
    ruts_consolidado=set(datos)
    if ruts_salud!=ruts_consolidado:
        invalidas.append('No coinciden los RUT entre Salud y las demás instituciones')
    # No propagar a todos los trabajadores una diferencia agregada de AFP o
    # Seguro Social: algunos trabajadores pueden tener regímenes o movimientos
    # distintos. Comparar por RUT y dejar hallazgos solo en filas afectadas.
    # Totales generales solo sirven como diagnóstico, no como pago acreditado.
    if not nombres_empleador or not rut_empleador or not periodo:
        invalidas.append('Falta información verificada de empleador o período en cabecera OCR')
    salida=[]
    for rut,fuentes_rut in sorted(datos.items()):
        obs=[]
        for t in ('salud','afp','mutual'):
            if not fuentes_rut.get(t):obs.append(f'Falta detalle {t}')
        def base(tipo):
            vals=fuentes_rut.get(tipo,[])
            return sum(x[2] for x in vals) if vals else None
        dia_s= sum(x[3] for x in fuentes_rut.get('salud',[]) if x[3] is not None) if fuentes_rut.get('salud') else None
        dia_ss=sum(x[3] for x in fuentes_rut.get('seguro_social',[]) if x[3] is not None) if fuentes_rut.get('seguro_social') else None
        if dia_s is not None and dia_ss is not None and dia_s!=dia_ss:
            obs.append('Días Salud no coinciden con Seguro Social')
        if any(not x[3] and x[3]!=0 for x in fuentes_rut.get('salud',[])):
            obs.append('Días de Salud ilegibles')
        rentas=[base('salud'),base('afp'),base('mutual')]
        if len({x for x in rentas if x is not None})>1:
            obs.append(
                'Bases imponibles distintas entre AFP, Salud y Mutual para este RUT; '
                'verificar régimen y documentos originales, no presumir impago'
            )
        # El Seguro Social tiene un ámbito que puede diferir del resto de las
        # instituciones. Su ausencia no invalida toda la nómina.
        if fuentes_rut.get('seguro_social'):
            if base('salud') is not None and base('seguro_social') != base('salud'):
                obs.append('Base Seguro Social distinta de Salud para este trabajador')
        elif 'seguro_social' in fuentes:
            obs.append('Trabajador sin fila de Seguro Social; verificar si corresponde cotizar')
        invalidas_de_este_rut = _advertencias_ocr_por_trabajador(invalidas, fuentes_rut)
        if invalidas_de_este_rut:
            obs.append('Verificar OCR: '+'; '.join(invalidas_de_este_rut[:8]))
        if not nombres.get(rut):
            obs.append('Nombre no confirmado en anexo Salud')
        paginas=sorted({r[0] for v in fuentes_rut.values() for r in v})
        # Si tres instituciones coinciden en la base, el RUT tiene nombre y
        # días válidos y no hay lecturas ambiguas, no crear una falsa alerta
        # solo porque el documento es imagen. Sigue sin probar pago efectivo.
        cotejo_ocr = bool(
            not obs and all(fuentes_rut.get(t) for t in ('salud','afp','mutual'))
            and all(x is not None and x > 0 for x in rentas)
            and len(set(rentas)) == 1 and dia_s is not None and 0 < dia_s <= 31
            and nombres.get(rut) and rut_empleador and periodo
        )
        if not cotejo_ocr:
            obs.append('OCR sin conciliación completa: cotejar páginas originales')
        salida.append({
            'periodo_remuneracion':periodo,
            'contratista_nombre':nombres_empleador,
            'contratista_rut':rut_empleador,
            'trabajador_nombre':nombres.get(rut,''),
            'trabajador_rut':rut,
            'dias_reales_pagados':dia_s if dia_s is not None else dia_ss,
            'renta_imponible_salud':base('salud'),
            'renta_imponible_afp':base('afp'),
            'renta_imponible_mutual':base('mutual'),
            'mutual_adherida':mutual,
            '__hoja_origen':', '.join(f'p.{z}' for z in paginas),
            '__ocr_estado': 'OCR_COTEJO_BASES_DIAS' if cotejo_ocr else 'OCR_REQUIERE_REVISION',
            '__conflicto_pdf':'; '.join(obs),
        })
    return pd.DataFrame(salida)
, mensaje)
        if not m:
            resultado.append(mensaje)
        elif 'RUT no reconocido' in mensaje or 'base imponible no reconocida' in mensaje:
            resultado.append(mensaje)
        elif (int(m.group(1)), int(m.group(2))) in referencias:
            resultado.append(mensaje)
    return list(dict.fromkeys(resultado))


def extraer_previred_escaneado_rapido(contenido:bytes,nombre:str) -> pd.DataFrame|None:
    """Extractor opcional para PREVIRED escaneado, no sustituye lectura digital.

    Devuelve None si el documento no coincide con el perfil de tablas; entonces
    entra el procesador estándar. Nunca emite 'CONFORME' sin respaldo total.
    """
    perfiles=_extraer_plantillas(contenido)
    tipos={p.tipo for p in perfiles}
    if not perfiles or len(tipos)<2 or 'salud' not in tipos:
        return None
    nombres_empleador,rut_empleador,periodo,mutual=_contexto(contenido,perfiles)
    datos:dict[str,dict[str,list[tuple[int,int,int|None,int|None]]]]=defaultdict(lambda:defaultdict(list))
    nombres: dict[str,str] = {}
    invalidas: list[str] = []
    salud_por_posicion: list[tuple[str,int|None,int|None]] = []
    # Primero Fonasa: su RUT y días sirven como control independiente de otras
    # instituciones, sin imponer su base como la base de AFP o Mutual.
    orden=sorted(perfiles,key=lambda p:0 if p.tipo=='salud' else 1)
    for p in orden:
        lote=_ocr_columna_digitos(p)
        nfilas=len(p.filas_y)
        # Una fuente con igual orden y número de filas puede utilizarse para
        # reconocer un RUT ilegible, pero solo si tres RUT válidos anclan el orden.
        puede_alinear=False
        if p.tipo in ('mutual','seguro_social') and len(salud_por_posicion)==nfilas:
            anclas=[(j,_rut(v.get('rut',''))) for j,v in enumerate(lote) if _rut(v.get('rut',''))]
            correctas=sum(1 for j,r in anclas if r==salud_por_posicion[j][0])
            puede_alinear=(correctas>=3 and correctas==len(anclas))
        for j,v in enumerate(lote):
            # La cabecera o el total no son trabajadores: evita OCR adicional.
            if not v.get('rut') and not v.get('renta') and not v.get('dias'):
                if p.tipo=='salud':
                    salud_por_posicion.append(('',None,None))
                continue
            rut=_rut(v.get('rut',''))
            if not rut:
                rut=_rut(_ocr_celda(p,'rut',j))
            if not rut and puede_alinear:
                rut=salud_por_posicion[j][0]
                if rut:
                    invalidas.append(f'p.{p.numero_pagina}, fila {j+1}: RUT alineado con Salud; cotejar visualmente')
            # En salud se puede corroborar por RUT; en las otras instituciones,
            # el esperado sirve únicamente para resolver discrepancias entre
            # montos *leídos realmente* en el propio recorte de esa fuente.
            esperado=None
            if p.tipo!='salud':
                val_salud=datos.get(rut,{}).get('salud',[])
                if val_salud:esperado=sum(row[2] for row in val_salud)
            cifra_lote=_renta(v.get('renta',''))
            # Una cifra coincidente en el OCR y en la fuente independiente
            # NO necesita otra invocación por celda; ahorro clave en nóminas grandes.
            if esperado is not None and cifra_lote==esperado:
                candidatos=[cifra_lote]
            else:
                cifra_2x=_ocr_num_con_escala(p,'renta',j,2.0)
                candidatos=[cifra_lote,cifra_2x]
                if (cifra_lote is None or cifra_2x is None or cifra_lote!=cifra_2x) and (esperado is None or esperado not in candidatos):
                    candidatos.append(_ocr_num_con_escala(p,'renta',j,3.0))
            renta,contradiccion=_seleccionar_valor(candidatos,esperado)
            if contradiccion:
                invalidas.append(f'p.{p.numero_pagina}, fila {j+1}: lecturas alternativas de renta {sorted(set(n for n in candidatos if n is not None))}; cotejar')
            dias=None
            if p.tipo=='salud':
                dias=_ocr_num_con_escala(p,'dias',j,2.0)
                # Para 11 días, a veces el OCR reconoce únicamente '1'.
                # Un segundo recorte independiente verifica los dos caracteres.
                if dias is None or dias==1:
                    alt=_ocr_num_con_escala(p,'dias',j,4.0)
                    if alt is not None and 0<=alt<=31:
                        dias=alt
                if dias is None:
                    dias=_renta(v.get('dias',''))
                if dias is None or dias>31:
                    invalidas.append(f'p.{p.numero_pagina}, fila {j+1}: días Salud no verificados')
                    dias=None
            elif p.tipo=='seguro_social':
                dias=_ocr_num_con_escala(p,'dias',j,1.5)
                # Las tablas muy pequeñas pueden confundir 6 con 5/8 y 11 con
                # 41; cotejar contra salud si se reconoce alternativamente.
                if dias is None or dias>31:
                    dias=_renta(v.get('dias',''))
                if dias is not None and dias>31:
                    dias=None
                ds=datos.get(rut,{}).get('salud',[])
                dia_esperado=sum(x[3] for x in ds if x[3] is not None) if ds else None
                if dia_esperado is not None and dias != dia_esperado:
                    # Segundo intento, sin copiar días de Salud a Seguro Social.
                    alternativas=[_ocr_num_con_escala(p,'dias',j,escala) for escala in (1.4,2.5,3.2)]
                    if dia_esperado in alternativas:
                        dias=dia_esperado  # leído en el SS por un segundo OCR
                    else:
                        # No copiar días de Salud a Seguro Social: se registra
                        # discrepancia para revisión humana.
                        invalidas.append(f'p.{p.numero_pagina}, fila {j+1}: días Seguro Social no concuerdan con Salud')
            if p.tipo=='salud':
                salud_por_posicion.append((rut,renta,dias))
            if not rut:
                if re.search(r'\d{5,}',v.get('rut','')):
                    invalidas.append(f'p.{p.numero_pagina}, fila {j+1}: RUT no reconocido')
                continue
            if renta is None:
                invalidas.append(f'p.{p.numero_pagina}, fila {j+1}: base imponible no reconocida')
                continue
            if dias is not None and not 0<=dias<=31:
                dias=None
            datos[rut][p.tipo].append((p.numero_pagina,j,renta,dias))
            if p.tipo=='salud':
                nombre=_nombre_salud(p,j)
                if nombre:nombres[rut]=nombre
    if not datos:
        raise ValueError('OCR escaneado detectó las tablas, pero no extrajo RUT y rentas verificables.')
    # Comprobar coherencia de todas las fuentes, incluidos registros omitidos.
    fuentes={t for t in tipos if t in ('salud','afp','mutual','seguro_social')}
    totales={t:sum(row[2] for por in datos.values() for row in por.get(t,[])) for t in fuentes}
    tam_fuentes={t:len({rut for rut,por in datos.items() if por.get(t)}) for t in fuentes}
    ruts_salud={rut for rut,fu in datos.items() if fu.get('salud')}
    ruts_consolidado=set(datos)
    if ruts_salud!=ruts_consolidado:
        invalidas.append('No coinciden los RUT entre Salud y las demás instituciones')
    # No propagar a todos los trabajadores una diferencia agregada de AFP o
    # Seguro Social: algunos trabajadores pueden tener regímenes o movimientos
    # distintos. Comparar por RUT y dejar hallazgos solo en filas afectadas.
    # Totales generales solo sirven como diagnóstico, no como pago acreditado.
    if not nombres_empleador or not rut_empleador or not periodo:
        invalidas.append('Falta información verificada de empleador o período en cabecera OCR')
    salida=[]
    for rut,fuentes_rut in sorted(datos.items()):
        obs=[]
        for t in ('salud','afp','mutual'):
            if not fuentes_rut.get(t):obs.append(f'Falta detalle {t}')
        def base(tipo):
            vals=fuentes_rut.get(tipo,[])
            return sum(x[2] for x in vals) if vals else None
        dia_s= sum(x[3] for x in fuentes_rut.get('salud',[]) if x[3] is not None) if fuentes_rut.get('salud') else None
        dia_ss=sum(x[3] for x in fuentes_rut.get('seguro_social',[]) if x[3] is not None) if fuentes_rut.get('seguro_social') else None
        if dia_s is not None and dia_ss is not None and dia_s!=dia_ss:
            obs.append('Días Salud no coinciden con Seguro Social')
        if any(not x[3] and x[3]!=0 for x in fuentes_rut.get('salud',[])):
            obs.append('Días de Salud ilegibles')
        rentas=[base('salud'),base('afp'),base('mutual')]
        if len({x for x in rentas if x is not None})>1:
            obs.append(
                'Bases imponibles distintas entre AFP, Salud y Mutual para este RUT; '
                'verificar régimen y documentos originales, no presumir impago'
            )
        # El Seguro Social tiene un ámbito que puede diferir del resto de las
        # instituciones. Su ausencia no invalida toda la nómina.
        if fuentes_rut.get('seguro_social'):
            if base('salud') is not None and base('seguro_social') != base('salud'):
                obs.append('Base Seguro Social distinta de Salud para este trabajador')
        elif 'seguro_social' in fuentes:
            obs.append('Trabajador sin fila de Seguro Social; verificar si corresponde cotizar')
        if invalidas:
            obs.append('Verificar OCR: '+'; '.join(dict.fromkeys(invalidas[:8])))
        if not nombres.get(rut):
            obs.append('Nombre no confirmado en anexo Salud')
        paginas=sorted({r[0] for v in fuentes_rut.values() for r in v})
        # Si tres instituciones coinciden en la base, el RUT tiene nombre y
        # días válidos y no hay lecturas ambiguas, no crear una falsa alerta
        # solo porque el documento es imagen. Sigue sin probar pago efectivo.
        cotejo_ocr = bool(
            not obs and all(fuentes_rut.get(t) for t in ('salud','afp','mutual'))
            and all(x is not None and x > 0 for x in rentas)
            and len(set(rentas)) == 1 and dia_s is not None and 0 < dia_s <= 31
            and nombres.get(rut) and rut_empleador and periodo
        )
        if not cotejo_ocr:
            obs.append('OCR sin conciliación completa: cotejar páginas originales')
        salida.append({
            'periodo_remuneracion':periodo,
            'contratista_nombre':nombres_empleador,
            'contratista_rut':rut_empleador,
            'trabajador_nombre':nombres.get(rut,''),
            'trabajador_rut':rut,
            'dias_reales_pagados':dia_s if dia_s is not None else dia_ss,
            'renta_imponible_salud':base('salud'),
            'renta_imponible_afp':base('afp'),
            'renta_imponible_mutual':base('mutual'),
            'mutual_adherida':mutual,
            '__hoja_origen':', '.join(f'p.{z}' for z in paginas),
            '__ocr_estado': 'OCR_COTEJO_BASES_DIAS' if cotejo_ocr else 'OCR_REQUIERE_REVISION',
            '__conflicto_pdf':'; '.join(obs),
        })
    return pd.DataFrame(salida)
