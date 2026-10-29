"""Extracción rápida de evidencia DOCUMENTAL de pago (no consulta bancos/Previred).
No depende del OCR de nóminas; una fecha ilegible nunca equivale a impago.
"""
from __future__ import annotations
import re
import unicodedata
from collections import OrderedDict
import fitz

MESES = {"enero":1,"febrero":2,"marzo":3,"abril":4,"mayo":5,"junio":6,"julio":7,"agosto":8,"septiembre":9,"setiembre":9,"octubre":10,"noviembre":11,"diciembre":12}
FECHA = r"([0-3]?\d\s*[/.-]\s*[01]?\d\s*[/.-]\s*20\d{2})"
PERIODO = r"((?:0?[1-9]|1[0-2])\s*[/.-]\s*20\d{2})"

def _flat(texto):
    return "".join(c for c in unicodedata.normalize("NFD", texto) if unicodedata.category(c)!="Mn").lower()

def _periodo(texto):
    t=_flat(texto)
    for pat in [
        r"(?:periodo\s*(?:de\s*)?(?:remuneraciones|cotizaciones)?|remuneracion\s*\(\s*mes)[\s:|]{0,25}"+PERIODO,
        r"\bperiodo\b[\s:|]{0,25}"+PERIODO,
        r"(?:periodo|remuneraciones)[\s\w:|]{0,55}?(?:0?([1-9]|1[0-2]))\s+20(\d{2})",
    ]:
        m=re.search(pat,t,re.I)
        if not m:continue
        if len(m.groups())==1:
            valor=re.sub(r"\s+","",m.group(1)).replace(".","/").replace("-","/")
            mes,ano=valor.split("/")
            return f"{ano}-{int(mes):02d}"
        if len(m.groups())==2:
            return f"20{m.group(2)}-{int(m.group(1)):02d}"
    for nombre,mes in MESES.items():
        m=re.search(r"\b"+nombre+r"\s+(20\d{2})\b",t)
        if m:return f"{m.group(1)}-{mes:02d}"
    # En escaneos la etiqueta "Periodo" puede perderse aunque quede "02/2026".
    # Solo aceptar un periodo aislado si hay exactamente un valor distinto.
    candidatos=re.findall(r"(?<!\d)((?:0?[1-9]|1[0-2])\s*[/.-]\s*20\d{2})(?!\d)",t)
    if len(set(candidatos))==1:
        mes,ano=re.split(r"[/.-]",candidatos[0])
        return f"{ano}-{int(mes):02d}"
    return ""

def _fecha_pago(texto):
    t=_flat(texto)
    for pat in [
        r"fecha\s*(?:de\s*)?pago\s*[:;]?\s*"+FECHA,
        r"pago\s+electronico\s*[:;|\s]{0,45}"+FECHA,
    ]:
        m=re.search(pat,t,re.I)
        if m:return re.sub(r"\s+","",m.group(1)).replace(".","/").replace("-","/")
    return ""

def _institucion(texto):
    t=_flat(texto)
    if "fonasa" in t:return "Fonasa"
    if "seguro social" in t:return "Seguro Social"
    if "instituto de seguridad laboral" in t or re.search(r"\bisl\b",t):return "ISL"
    if "asociacion chilena de seguridad" in t or re.search(r"\bachs\b",t):return "ACHS"
    if "mutual de seguridad" in t:return "Mutual"
    m=re.search(r"\bafp\s+(planvital|provida|modelo|habitat|capital|cuprum|uno|simple)\b",t)
    return "AFP "+m.group(1).capitalize() if m else "Institución no identificada"

def _folio(texto):
    m=re.search(r"(?:numero\s+(?:de\s+)?(?:folio|serie)|n[o°]\s*folio)\s*[:#]?\s*(\d{12,20})",_flat(texto))
    return m.group(1) if m else ""

def _interpretar(texto,pagina,fuente):
    t=_flat(texto)
    # OCR imperfecto: 'electrénico' y el folio siguen siendo evidencia del formato.
    # Requerir dos anclas independientes; no inferir pago sin fecha concreta.
    hay_formato=any(k in t for k in ("cotizaciones","pago elec","monto pagado","periodo de remuneracion"))
    hay_origen=any(k in t for k in ("previred","numero de folio","ngmero de folio"))
    if not (hay_formato and hay_origen):
        return None
    fecha=_fecha_pago(texto)
    periodo=_periodo(texto)
    # Las casillas de Fonasa imprimen "Declaración y no pago" aunque NO estén marcadas.
    # Considerar la condición solo cuando aparezca en el TÍTULO del comprobante.
    declaracion_sin_pago=("comprobante de declaracion y no pago" in t or
                          "comprobante de declaracion y no de pago" in t)
    # OCR frecuentemente convierte "Electrónico" en "Electrénico".
    # La presencia de FECHA DE PAGO en comprobante PREVIRED también es evidencia.
    pago_con_respaldo=bool(fecha and any(
        clave in t for clave in ("pago electr","fecha pago","monto pagado")
    ))
    if pago_con_respaldo:
        estado=("PAGO_POSTERIOR_DOCUMENTADO_REVISAR" if declaracion_sin_pago
                else "PAGO_RESPALDADO_EN_DOCUMENTO")
    elif declaracion_sin_pago:
        estado="DECLARACION_SIN_PAGO_IDENTIFICADO"
    else:
        estado="EVIDENCIA_INSUFICIENTE"
    return {"pagina":pagina,"fuente":fuente,"institucion":_institucion(texto),
        "folio":_folio(texto),"periodo":periodo,
        "fecha_pago":fecha if pago_con_respaldo else "",
        "estado":estado,"observacion":(
          "El encabezado menciona declaración y no pago, pero hay fecha de pago; revisar regularización."
          if pago_con_respaldo and declaracion_sin_pago else "")}

def _fecha_espacial(datos, ancho, alto):
    """Asocia la fecha al CUADRO de pago por proximidad visual."""
    palabras=[str(x).lower() for x in datos["text"]]
    for i, palabra in enumerate(palabras):
        if palabra!="pago" or float(datos["conf"][i])<35:
            continue
        x=datos["left"][i]/ancho
        y=datos["top"][i]/alto
        acompana=any(
            re.match(r"elec|electr",valor)
            and abs(datos["top"][j]/alto-y)<0.025
            and 0<datos["left"][j]/ancho-x<0.18
            for j,valor in enumerate(palabras)
        )
        if not acompana:
            continue
        opciones=[]
        for j,valor in enumerate(palabras):
            if not re.fullmatch(r"[0-3]?\d[/.-][01]?\d[/.-]20\d{2}",valor):
                continue
            distancia_y=datos["top"][j]/alto-y
            distancia_x=abs(datos["left"][j]/ancho-x)
            if distancia_x<0.18 and -0.01<distancia_y<0.10 and float(datos["conf"][j])>=45:
                opciones.append((distancia_y,valor))
        if opciones:
            return sorted(opciones)[0][1].replace(".","/").replace("-","/")
    return ""

def _periodo_espacial(datos, ancho, alto):
    """Reconoce '09 2026' en celdas contiguas cuando el OCR separa columnas."""
    posibles=[]
    for i,ano in enumerate(datos["text"]):
        if not re.fullmatch(r"20\d{2}",str(ano)):
            continue
        x=datos["left"][i]/ancho
        y=datos["top"][i]/alto
        for j,mes in enumerate(datos["text"]):
            if not re.fullmatch(r"(?:0?[1-9]|1[0-2])",str(mes)):
                continue
            dx=datos["left"][j]/ancho-x
            dy=abs(datos["top"][j]/alto-y)
            if -0.12<dx<0 and dy<0.015 and float(datos["conf"][j])>=35:
                posibles.append((dy,f"{ano}-{int(mes):02d}"))
    return sorted(posibles)[0][1] if posibles else ""

def _ocr_portada(pagina, orientacion_previa=None):
    """Un OCR espacial por orientación candidata; alternar solo si hace falta."""
    from PIL import Image
    import pytesseract
    from collections import OrderedDict
    pix=pagina.get_pixmap(matrix=fitz.Matrix(1.9,1.9),
                          colorspace=fitz.csGRAY,alpha=False)
    im=Image.frombytes("L",(pix.width,pix.height),pix.samples)
    opciones=([orientacion_previa] if orientacion_previa is not None else [])
    opciones+=([90,270,0] if im.height>im.width else [0,180])
    texto_mejor,rotacion_mejor,pago_mejor,periodo_mejor="",None,"",""
    puntuacion_mejor=-1
    for rot in dict.fromkeys(opciones):
        foto=im.rotate(rot,expand=True) if rot else im
        try:
            datos=pytesseract.image_to_data(
                foto,lang="eng",config="--oem 1 --psm 11",
                timeout=8,output_type=pytesseract.Output.DICT)
        except (RuntimeError,OSError):
            continue
        lineas=OrderedDict()
        for j,palabra in enumerate(datos["text"]):
            if not str(palabra).strip():
                continue
            clave=(datos["block_num"][j],datos["par_num"][j],datos["line_num"][j])
            lineas.setdefault(clave,[]).append(str(palabra))
        texto="\n".join(" ".join(linea) for linea in lineas.values())
        pago=_fecha_espacial(datos,foto.width,foto.height)
        periodo=_periodo_espacial(datos,foto.width,foto.height)
        puntuacion=sum(2 for k in ("previred","pago electronico","periodo",
                                     "remuneraciones","cotizaciones")
                       if k in _flat(texto))+(3 if pago else 0)
        if puntuacion>puntuacion_mejor:
            texto_mejor,rotacion_mejor,pago_mejor,periodo_mejor=texto,rot,pago,periodo
            puntuacion_mejor=puntuacion
        if puntuacion>=9:
            break
    return texto_mejor,rotacion_mejor,pago_mejor,periodo_mejor

def _ocr_detalle_cabecera(pagina, orientacion=None):
    """OCR en solo el 38 % superior de un detalle: no escanea nóminas."""
    from PIL import Image
    import pytesseract
    pix=pagina.get_pixmap(matrix=fitz.Matrix(1.9,1.9),colorspace=fitz.csGRAY,alpha=False)
    img=Image.frombytes("L",(pix.width,pix.height),pix.samples)
    giros=([orientacion] if orientacion is not None else [])
    giros+=([90,270] if img.height>img.width else [0,180])
    mejor,puntaje="",-1
    for giro in dict.fromkeys(giros):
        foto=img.rotate(giro,expand=True) if giro else img
        cab=foto.crop((0,0,foto.width,int(foto.height*.38)))
        try:
            texto=pytesseract.image_to_string(
                cab,lang="eng",config="--oem 1 --psm 11",timeout=5)
        except (RuntimeError,OSError):
            continue
        punt=sum(3 for k in ("periodo","remuneraciones","pago electr","previred")
                 if k in _flat(texto))
        if punt>puntaje:mejor,puntaje=texto,punt
        if punt>=9:break
    return mejor


def analizar_pago_pdf(contenido:bytes,nombre:str="",max_paginas_ocr:int=6):
    """Devuelve evidencias por folio; procesamiento parcial explícito.
    Escaneos: analizar prioritariamente páginas impares (portadas).
    No declara el archivo completo PAGADO si no leyó sus instituciones.
    """
    evidencias=[]
    with fitz.open(stream=contenido,filetype="pdf") as pdf:
        texto_digital=0;paginas_imagen=0;paginas_ocr=0;orientacion=None
        for indice,pagina in enumerate(pdf):
            texto=pagina.get_text("text",sort=False)
            if len(texto.strip())>=90:
                texto_digital+=1
                e=_interpretar(texto,indice+1,"texto PDF")
                if e:evidencias.append(e)
                continue
            paginas_imagen+=1
            if indice%2!=0 or paginas_ocr>=max_paginas_ocr:
                continue
            paginas_ocr+=1
            texto,orientacion,fecha_visual,periodo_visual=_ocr_portada(pagina,orientacion)
            e=_interpretar(texto,indice+1,"OCR")
            if e:
                if periodo_visual and not e["periodo"]:
                    e["periodo"]=periodo_visual
                if fecha_visual and not e["fecha_pago"]:
                    e["fecha_pago"]=fecha_visual
                    titulo_no_pago=("comprobante de declaracion y no pago" in _flat(texto)
                                    or "comprobante de declaracion y no de pago" in _flat(texto))
                    e["estado"]=("PAGO_POSTERIOR_DOCUMENTADO_REVISAR"
                                  if titulo_no_pago else "PAGO_RESPALDADO_EN_DOCUMENTO")
                evidencias.append(e)
        # Una compilación puede comenzar con DETALLE: no siempre hay portadas impares.
        # Rescate acotado, solo si faltan comprobantes y hay presupuesto OCR.
        if paginas_imagen and len(evidencias)<3 and paginas_ocr<max_paginas_ocr:
            for indice,pagina in enumerate(pdf):
                if indice%2==0 or pagina.get_text("text").strip() or paginas_ocr>=max_paginas_ocr:
                    continue
                paginas_ocr+=1
                texto,_,fecha_visual,periodo_visual=_ocr_portada(pagina,orientacion)
                ev=_interpretar(texto,indice+1,"OCR")
                if not ev:continue
                if periodo_visual and not ev["periodo"]:ev["periodo"]=periodo_visual
                if fecha_visual and not ev["fecha_pago"]:
                    ev["fecha_pago"]=fecha_visual
                    ev["estado"]="PAGO_RESPALDADO_EN_DOCUMENTO"
                evidencias.append(ev)
                if len(evidencias)>=3:break
        # Rescate opcional de fecha/período desde la página de detalle.
        # Una hoja adyacente puede ser OTRA institución: exigir mismo folio.
        for ev in evidencias:
            if ev["fuente"]!="OCR" or not ev["folio"] or (
                ev["fecha_pago"] and ev["periodo"] and
                not ev["institucion"].startswith("Institución")
            ):
                continue
            i=ev["pagina"]
            if i>=len(pdf) or i%2!=1 or pdf[i].get_text("text").strip():
                continue
            texto_det=_ocr_detalle_cabecera(pdf[i])
            folio_det=_folio(texto_det)
            if not folio_det or folio_det!=ev["folio"]:
                continue
            periodo_det=_periodo(texto_det)
            if periodo_det and not ev["periodo"]:ev["periodo"]=periodo_det
            fecha_det=_fecha_pago(texto_det)
            if (fecha_det and not ev["fecha_pago"] and
                    ("pago elec" in _flat(texto_det) or "fecha pago" in _flat(texto_det))):
                ev["fecha_pago"]=fecha_det
                ev["estado"]="PAGO_RESPALDADO_EN_DOCUMENTO"
            if ev["institucion"].startswith("Institución"):
                instituto=_institucion(texto_det)
                if not instituto.startswith("Institución"):ev["institucion"]=instituto
        # Una página de resumen y su detalle pueden compartir folio.
        por_folio=OrderedDict()
        for e in evidencias:
            clave=e["folio"] or (e["institucion"],e["periodo"],e["fecha_pago"],e["estado"])
            if clave not in por_folio or (not por_folio[clave]["fecha_pago"] and e["fecha_pago"]):
                por_folio[clave]=e
        return {"archivo":nombre,"paginas":len(pdf),
            "paginas_texto_digital":texto_digital,"paginas_imagen":paginas_imagen,
            "paginas_ocr":paginas_ocr,
            "revision_integral":paginas_imagen==0,
            "cobertura":"COMPLETA_TEXTO" if paginas_imagen==0 else "OCR_PARCIAL",
            "comprobantes":list(por_folio.values())}
