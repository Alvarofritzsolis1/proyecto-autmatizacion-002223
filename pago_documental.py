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
    if not ("previred" in t and any(k in t for k in ("cotizaciones","pago electronico","monto pagado"))):
        return None
    fecha=_fecha_pago(texto)
    periodo=_periodo(texto)
    # Las casillas de Fonasa imprimen "Declaración y no pago" aunque NO estén marcadas.
    # Considerar la condición solo cuando aparezca en el TÍTULO del comprobante.
    declaracion_sin_pago=("comprobante de declaracion y no pago" in t or
                          "comprobante de declaracion y no de pago" in t)
    pago_con_respaldo=bool(fecha and ("pago electronico" in t or
        "declaracion electronica y pago" in t or "monto pagado" in t))
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

def _ocr_portada(pagina, orientacion_previa=None):
    """OCR limitado a portadas, con prueba de rotación inversa si falla."""
    from PIL import Image
    import pytesseract
    pix=pagina.get_pixmap(matrix=fitz.Matrix(1.8,1.8),
                          colorspace=fitz.csGRAY,alpha=False)
    im=Image.frombytes("L",(pix.width,pix.height),pix.samples)
    opciones=([orientacion_previa] if orientacion_previa is not None else [])
    opciones+=([90,270,0] if im.height>im.width else [0,180])
    mejor,mejor_rotacion,mejor_puntaje="",None,-1
    for rot in dict.fromkeys(opciones):
        img=im.rotate(rot,expand=True) if rot else im
        try:
            texto=pytesseract.image_to_string(
                img,lang="eng",config="--oem 1 --psm 11",timeout=8)
        except (RuntimeError,OSError):
            continue
        score=sum(2 for k in ("previred","pago electronico","periodo",
                               "remuneraciones","cotizaciones")
                  if k in _flat(texto))
        if score>mejor_puntaje:
            mejor,mejor_rotacion,mejor_puntaje=texto,rot,score
        if score>=6:
            break
    return mejor,mejor_rotacion

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
            texto,orientacion=_ocr_portada(pagina,orientacion)
            e=_interpretar(texto,indice+1,"OCR")
            if e:evidencias.append(e)
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
            "comprobantes":list(por_folio.values())}
