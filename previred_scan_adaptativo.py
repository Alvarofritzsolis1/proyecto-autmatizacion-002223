"""OCR estructural de anexos Previred escaneados/girados.

Lector adaptativo para planillas cuando el OCR general reconoce texto pero no
la retícula. Coteja RUT por DV y bases entre instituciones. No acredita pago.
"""
from __future__ import annotations
from collections import Counter, defaultdict
from dataclasses import dataclass
import re
import fitz
import cv2
import numpy as np
import pandas as pd
from PIL import Image, ImageOps
from previred_pdf import _rut_clean, _rut_ok

CAMPOS = {
    'salud': {'rut':(1,2),'nombre':(2,5),'dias':(5,6),'base':(7,8)},
    'seguro_social': {'rut':(1,2),'nombre':(2,3),'base':(3,4),'dias':(9,10)},
    'afp': {'rut':(0,1),'nombre':(1,2),'base':(2,3),'cesantia':(9,10)},
    'mutual': {'rut':(0,1),'nombre':(1,4),'base':(4,5)},
}

@dataclass
class Anexo:
    tipo: str
    pagina: int
    img: Image.Image
    filas: list[tuple[int,int]]
    verticales: list[int]
    periodo: str
    folio: str


def _grupos(indices: np.ndarray, salto=2) -> list[list[int]]:
    salida = []
    for numero in indices:
        n = int(numero)
        if not salida or n > salida[-1][-1] + salto:
            salida.append([n])
        else:
            salida[-1].append(n)
    return salida


def _lectura(crop: Image.Image, config: str, *, timeout=4) -> str:
    import pytesseract
    try:
        return pytesseract.image_to_string(
            crop,lang='eng',config='--oem 1 '+config,timeout=timeout
        ).strip()
    except (RuntimeError,OSError):
        return ''


def _pagina_horizontal(pagina, escala=2.3):
    p = pagina.get_pixmap(
        matrix=fitz.Matrix(escala,escala),colorspace=fitz.csGRAY,alpha=False
    )
    img = Image.frombytes('L',(p.width,p.height),p.samples)
    return img.rotate(90,expand=True) if img.height>img.width else img


def _tipo(texto: str) -> str:
    t = texto.lower()
    if 'seguro social' in t and 'previsional' in t:
        return 'seguro_social'
    if 'fonasa' in t or ('anexos de detalle' in t and 'cotizacion 7' in t):
        return 'salud'
    if 'achs' in t or 'asociacion chilena de seguridad' in t:
        return 'mutual'
    if ('afp' in t or 'fondo de pensiones' in t) and 'detalle' in t:
        return 'afp'
    return ''


def _filas_y(im: Image.Image) -> list[tuple[int,int]]:
    a = np.asarray(im)
    h,w = a.shape
    inv = cv2.threshold(a,175,255,cv2.THRESH_BINARY_INV)[1]
    k = max(36,int(w*.045))
    horizontales = cv2.morphologyEx(
        inv,cv2.MORPH_OPEN,cv2.getStructuringElement(cv2.MORPH_RECT,(k,1))
    )
    cont,_ = cv2.findContours(horizontales,cv2.RETR_EXTERNAL,cv2.CHAIN_APPROX_SIMPLE)
    lineas = []
    for c in cont:
        x,y,ancho,alto = cv2.boundingRect(c)
        if ancho>=w*.80 and h*.15<y<h*.52 and alto<25:
            lineas.append(y)
    lineas = sorted(set(lineas))
    cadenas=[]
    for inicio in range(len(lineas)):
        secuencia=[lineas[inicio]]
        for siguiente in lineas[inicio+1:]:
            distancia=siguiente-secuencia[-1]
            if 12<=distancia<=31:
                secuencia.append(siguiente)
            else:
                break
        if len(secuencia)>=3:
            cadenas.append(secuencia)
    if not cadenas:
        return []
    mejor=max(cadenas,key=lambda xs:(len(xs),-xs[0]))
    if len(mejor)>120:
        return []
    return list(zip(mejor[:-1],mejor[1:]))


def _columnas(im: Image.Image,filas: list[tuple[int,int]]) -> list[int]:
    a=np.asarray(im)
    alto,ancho=a.shape
    ya,yb=filas[0][0],filas[-1][1]
    rec=(a[max(0,ya-2):min(alto,yb+2)]<170).astype('uint8')*255
    longitud=max(10,min(24,int((yb-ya)*.35)))
    vertical=cv2.morphologyEx(
        rec,cv2.MORPH_OPEN,cv2.getStructuringElement(cv2.MORPH_RECT,(1,longitud))
    )
    xs=np.flatnonzero(vertical.sum(axis=0)/255>(yb-ya)*.38)
    bordes=[int(round(np.median(g))) for g in _grupos(xs)]
    if len(bordes)<9 or bordes[0]>ancho*.10 or bordes[-1]<ancho*.8:
        return []
    return bordes


def _rangos_col(a: Anexo,campo: str):
    spec=CAMPOS[a.tipo].get(campo)
    if not spec:
        return None
    i,j=spec
    if j>=len(a.verticales):
        return None
    return a.verticales[i],a.verticales[j]


def _recorte(a: Anexo,fila: int,campo: str,escala: float=1.):
    xr=_rangos_col(a,campo)
    if not xr:
        return None
    x1,x2=xr
    y1,y2=a.filas[fila]
    crop=a.img.crop((x1+5,y1+7,x2-5,y2+8))
    if crop.width<8 or crop.height<8:
        return None
    if escala!=1:
        crop=crop.resize(
            (max(1,int(crop.width*escala)),max(1,int(crop.height*escala))),
            Image.Resampling.BICUBIC
        )
    return ImageOps.autocontrast(crop)


def _rut_ocr(s):
    return re.sub(r'[^0-9K]','',str(s).upper())


def _numeros_ocr(s):
    t=re.sub(r'[^0-9.]','',s or '')
    if not t or not re.fullmatch(r'\d{1,3}(?:\.\d{3})+|\d+',t):
        return None
    return int(t.replace('.',''))


def _observaciones(a: Anexo,i: int):
    ruts,bases,dias,cesantia=[],[],[],[]
    for escala in (1.0,1.4):
        for campo,destino in (
            ('rut',ruts),('base',bases),('dias',dias),('cesantia',cesantia)
        ):
            crop=_recorte(a,i,campo,escala=escala*3)
            if crop is None:
                continue
            config=(
                '--psm 7 -c tessedit_char_whitelist=0123456789.K-'
                if campo=='rut' else
                '--psm 7 -c tessedit_char_whitelist=0123456789.'
            )
            texto=_lectura(crop,config)
            if campo=='rut':
                rut=_rut_ocr(texto)
                if len(rut) in (8,9):
                    destino.append(rut)
            else:
                n=_numeros_ocr(texto)
                if n is not None:
                    destino.append(n)
    if a.tipo=='afp' and not bases:
        # No sustituir el fondo AFP por el imponible de Seguro Cesantía.
        xr=_rangos_col(a,'base')
        if xr:
            _,borde=xr
            ya,yb=a.filas[i]
            glifo=a.img.crop((borde-16,ya+6,borde,yb+8))
            glifo=ImageOps.autocontrast(
                glifo.resize((glifo.width*8,glifo.height*8))
            )
            lienzo=Image.new('L',(glifo.width+45,glifo.height+45),255)
            lienzo.paste(glifo,(20,20))
            if any(
                t.strip().strip('_.,| ')=='0'
                for t in (_lectura(lienzo,'--psm 7'),
                          _lectura(lienzo,'--psm 10'))
            ):
                bases=[0,0]
    nombre=''
    if a.tipo=='salud':
        partes=[]
        for izq,der in ((2,3),(3,4),(4,5)):
            xs=a.verticales
            ya,yb=a.filas[i]
            c=a.img.crop((xs[izq]+4,ya+6,xs[der]-4,yb+8))
            c=ImageOps.autocontrast(c.resize((c.width*4,c.height*4)))
            pal=_lectura(c,'--psm 7')
            pal=' '.join(re.findall(r'[A-Za-zÁÉÍÓÚÑÜáéíóúñü]+',pal)).upper()
            if pal and (len(pal)>=3 or pal in {'DE','LA'}):
                partes.append(pal)
        nombre=' '.join(partes)
    return dict(
        pagina=a.pagina,tipo=a.tipo,folio=a.folio,ruts=ruts,bases=bases,
        dias=dias,cesantia=cesantia,nombre=nombre
    )


def _mas_comun(valores):
    if not valores:
        return None
    frecuencia=Counter(valores)
    return max(frecuencia,key=lambda v:(frecuencia[v],v))


def _resolver_rut(obs: dict,anclas: set[str]):
    candidatos=[r for r in obs['ruts'] if _rut_ok(r)]
    if candidatos:
        cuenta=Counter(candidatos)
        return max(cuenta,key=lambda x:(cuenta[x],x in anclas)),False
    posibles=[]
    for crudo in obs['ruts']:
        for valido in anclas:
            if len(crudo)==len(valido) and sum(
                x!=y for x,y in zip(crudo,valido)
            )<=1:
                posibles.append(valido)
    if len(set(posibles))==1:
        return posibles[0],True
    return '',False


def _extraer_paginas(pdf):
    anexos,diagnosticos=[],[]
    if pdf.page_count>120:
        raise ValueError('PDF demasiado largo para OCR interactivo')
    for idx,pagina in enumerate(pdf):
        if len(pagina.get_text().strip())>120:
            return [],[]
        img=_pagina_horizontal(pagina)
        w,h=img.size
        texto=_lectura(img.crop((0,0,w,int(h*.24))),'--psm 6',timeout=5)
        tipo=_tipo(texto)
        if not tipo:
            continue
        if (tipo!='seguro_social' and 'detalle' not in texto.lower()
                and 'anexos' not in texto.lower()):
            continue
        filas=_filas_y(img)
        if not filas:
            diagnosticos.append(f'p.{idx+1}: faltan filas de {tipo}')
            continue
        xs=_columnas(img,filas)
        if not xs:
            diagnosticos.append(f'p.{idx+1}: columnas de {tipo} ilegibles')
            continue
        if not all(CAMPOS[tipo][campo][1]<len(xs) for campo in ('rut','base')):
            diagnosticos.append(f'p.{idx+1}: columnas incompletas')
            continue
        m=re.search(
            r'(?:per[ií]?od\w*\s+de\s+remuneraciones?)\s*[:;]?\s*'
            r'(0?[1-9]|1[0-2])\s*[/.-]\s*(20\d{2})',
            texto,re.I
        )
        periodo=f'{m.group(2)}-{int(m.group(1)):02d}' if m else ''
        folio_m=re.search(r'(\d{13,18})',texto)
        folio=folio_m.group(1) if folio_m else ''
        anexos.append(Anexo(tipo,idx+1,img,filas,xs,periodo,folio))
    return anexos,diagnosticos


def extraer_previred_scan_adaptativo(contenido: bytes,nombre: str):
    """Extrae RUT y campos individuales de retículas giradas/escaneadas."""
    with fitz.open(stream=contenido,filetype='pdf') as pdf:
        anexos,problemas=_extraer_paginas(pdf)
    tipos={a.tipo for a in anexos}
    if not {'salud','mutual'}.issubset(tipos) or not (
        {'afp','seguro_social'} & tipos
    ):
        return None
    observaciones=[]
    for a in anexos:
        for i in range(len(a.filas)):
            obs=_observaciones(a,i)
            if obs['ruts'] or obs['bases']:
                observaciones.append(obs)
    anclas={
        r for obs in observaciones for r in obs['ruts'] if _rut_ok(r)
    }
    if len(anclas)<2:
        return None
    agrupado=defaultdict(lambda:defaultdict(list))
    nombres={}
    incidencias=defaultdict(list)
    sin_rut=[]
    for obs in observaciones:
        rut,corregido=_resolver_rut(obs,anclas)
        if not rut:
            sin_rut.append(f'p.{obs["pagina"]}: RUT ilegible en {obs["tipo"]}')
            continue
        obs['rut']=rut
        if corregido:
            obs['rut_cotejado']=True
        agrupado[rut][obs['tipo']].append(obs)
        if obs['nombre'] and len(obs['nombre'])>8:
            nombres[rut]=obs['nombre']
    if not agrupado:
        return None
    for rut,fuentes in agrupado.items():
        confirmados=Counter(
            n for registros in fuentes.values()
            for obs in registros for n in obs['bases'] if n>0
        )
        for registros in fuentes.values():
            for obs in registros:
                valores=list(dict.fromkeys(obs['bases']))
                validos=[n for n in valores if confirmados[n]>=2]
                obs['base_elegida']=(
                    validos[0] if len(validos)==1
                    else _mas_comun(obs['bases'])
                )
                if len(valores)>1 and not validos:
                    incidencias[rut].append(
                        f'p.{obs["pagina"]}: alternativas OCR {obs["tipo"]} {valores}'
                    )
                dias_validos=[v for v in obs['dias'] if 0<=v<=31]
                obs['dias_elegidos']=_mas_comun(dias_validos)
    periodos={a.periodo for a in anexos if a.periodo}
    periodo=next(iter(periodos)) if len(periodos)==1 else ''
    if len(periodos)>1:
        problemas.append('Períodos distintos entre instituciones')
    salud=next(a for a in anexos if a.tipo=='salud')
    w,h=salud.img.size
    cab=_lectura(
        salud.img.crop(
            (int(w*.10),int(h*.15),int(w*.53),int(h*.25))
        ).resize((int(w*.86),int(h*.20))),'--psm 6'
    )
    m=re.search(
        r'(\d{1,2}[. ]?\d{3}[. ]?\d{3}\s*[-–]\s*[0-9Kk])',cab
    )
    rut_empresa=(
        _rut_clean(m.group(1))
        if m and _rut_ok(_rut_clean(m.group(1))) else ''
    )
    nombre_empresa=''
    m=re.search(r'(?:RAZON\s+SOCIAL\s+O\s+)?NOMBRE\s+(.+)',cab,re.I)
    if m:
        nombre_empresa=m.group(1).splitlines()[0].strip(' _.').upper()
    if not nombre_empresa:
        nombre_empresa='CONTRATISTA NO IDENTIFICADO'
    salida=[]
    for rut,fuentes in sorted(agrupado.items()):
        def monto(tipo):
            registros=fuentes.get(tipo,[])
            vals=[o.get('base_elegida') for o in registros]
            return (
                sum(vals) if registros and all(v is not None for v in vals)
                else None
            )
        def dias(tipo):
            registros=fuentes.get(tipo,[])
            vals=[o.get('dias_elegidos') for o in registros]
            return (
                sum(vals) if registros and all(v is not None for v in vals)
                else None
            )
        sal,afp,mut=monto('salud'),monto('afp'),monto('mutual')
        ss=monto('seguro_social')
        ds,dss=dias('salud'),dias('seguro_social')
        d=ds if ds is not None else dss
        notas=list(dict.fromkeys(incidencias[rut]))
        if not periodo:
            notas.append('Período no confirmado en el PDF')
        if not rut_empresa:
            notas.append('RUT empleador sin validar')
        if sal is None:
            notas.append('No se reconoció imponible Fonasa')
        if mut is None:
            notas.append('No se reconoció imponible Mutual')
        if afp is None:
            notas.append('No se reconoció fondo AFP')
        elif afp==0 and sal and sal>0:
            ces=sum(
                (_mas_comun(o['cesantia']) or 0)
                for o in fuentes.get('afp',[])
            )
            notas.append(
                'Fondo AFP cero, Salud '+str(sal)+
                ', Seguro Cesantía '+str(ces)+
                '; verificar régimen o exención, no presumir impago'
            )
        if ds is not None and dss is not None and ds!=dss:
            notas.append('Días Fonasa y Seguro Social no coinciden')
        if sal is not None and mut is not None and sal!=mut:
            notas.append('Bases Salud y Mutual no coinciden')
        if sal is not None and afp is not None and sal!=afp and afp>0:
            notas.append('Bases AFP y Salud no coinciden')
        paginas=sorted({
            o['pagina'] for registros in fuentes.values() for o in registros
        })
        salida.append(dict(
            periodo_remuneracion=periodo,
            contratista_nombre=nombre_empresa,contratista_rut=rut_empresa,
            trabajador_nombre=nombres.get(rut,'NOMBRE EN REVISIÓN OCR'),
            trabajador_rut=rut,dias_reales_pagados=d,
            renta_imponible_salud=sal,renta_imponible_afp=afp,
            renta_imponible_mutual=mut,mutual_adherida='ACHS',
            __hoja_origen=', '.join('p.'+str(p) for p in paginas),
            __conflicto_pdf='; '.join(notas),
            __cobertura_seguro_social=(
                'PRESENTE_SS' if ss is not None else 'SIN_REGISTRO_SS'
            ),
            __renta_seguro_social=ss,
            __ocr_evidencia='Fuentes: '+', '.join(sorted(fuentes)),
            __ocr_estado=(
                'OCR_COTEJO_ESTRUCTURAL' if not notas
                else 'OCR_REQUIERE_REVISION'
            ),
            __observaciones_archivo='; '.join(problemas+sin_rut)
        ))
    df=pd.DataFrame(salida)
    df.attrs['diagnostico_ocr']=dict(
        paginas_detectadas=[a.pagina for a in anexos],
        fuentes_detectadas=sorted(tipos),rut_sin_asignar=sin_rut,
        filas_por_pagina={a.pagina:len(a.filas) for a in anexos}
    )
    return df
