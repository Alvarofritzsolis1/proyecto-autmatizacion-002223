"""OCR híbrido local y evaluación CONSERVADORA de evidencia de pago.
No confirma operaciones bancarias, Previred ni instituciones previsionales.
"""
from __future__ import annotations
import re
import unicodedata
from pathlib import Path
import fitz
import pytesseract
from PIL import Image, ImageOps, ImageFilter
from .config import get_settings

MONTHS = dict(zip('enero febrero marzo abril mayo junio julio agosto septiembre octubre noviembre diciembre'.split(), range(1,13)))
MONTHS['setiembre'] = 9
STATES = {
    'paid':'Pago acreditado documentalmente',
    'none':'Pago no acreditado',
    'review':'Pendiente de revisión',
    'unreadable':'Documento ilegible',
    'wrong':'Documento incorrecto',
}

def normalize(value: str) -> str:
    return ''.join(c for c in unicodedata.normalize('NFKD', value.lower()) if not unicodedata.combining(c))

def rut_is_valid(value: str) -> bool:
    rut = re.sub(r'[^\dkK]', '', value).upper()
    if len(rut) < 2 or not rut[:-1].isdigit():
        return False
    digits = [int(c) for c in rut[:-1]][::-1]
    dv = 11 - sum(x*(2+i%6) for i,x in enumerate(digits))%11
    expected = '0' if dv == 11 else 'K' if dv == 10 else str(dv)
    return rut[-1] == expected

def find_ruts(value: str) -> list[str]:
    pattern = r'(?<!\d)(\d{1,2}[.]?\d{3}[.]?\d{3}[-\s]?[\dkK])(?!\w)'
    output = []
    for candidate in re.findall(pattern, value):
        if rut_is_valid(candidate):
            digits = re.sub(r'[^\dkK]','',candidate).upper()
            normalized = f'{int(digits[:-1]):,}'.replace(',','.')+'-'+digits[-1]
            if normalized not in output: output.append(normalized)
    return output[:150]

def detect_period(value: str) -> str | None:
    t = normalize(value)
    for pattern in (
        r'(?:periodo|mes)\s*(?:de\s*)?(?:remuneracion(?:es)?|cotizacion(?:es)?|previsional)?\s*[:\-]?\s*(0?[1-9]|1[0-2])\s*[/\-]\s*(20\d{2})',
        r'(?:periodo|mes)\s*(?:de\s*)?(?:remuneracion(?:es)?|cotizacion(?:es)?|previsional)?\s*[:\-]?\s*([a-z]+)\s*(?:de\s*)?(20\d{2})',
    ):
        match = re.search(pattern,t)
        if match:
            month = int(match[1]) if match[1].isdigit() else MONTHS.get(match[1])
            if month: return f'{match[2]}-{month:02}'
    return None

def detect_type(value: str) -> str:
    t = normalize(value)
    if any(x in t for x in ('f30-1','f30 1','certificado de cumplimiento de obligaciones laborales')): return 'f30_1'
    if 'trabajador independiente' in t or 'cotizante independiente' in t: return 'independientes'
    if any(x in t for x in ('previred','cotizaciones previsionales','comprobante de pago','planilla de cotizaciones','fonasa','isapre','afp')): return 'cotizaciones'
    return 'desconocido'

def assess_payment(value: str, period: str | None, kind: str, readable: bool) -> tuple[str,list[str]]:
    if not readable: return STATES['unreadable'], ['Texto insuficiente o ilegible']
    if kind == 'desconocido': return STATES['wrong'], ['No se identificó documento previsional']
    if kind == 'f30_1': return STATES['review'], ['F30-1 es un certificado: no acredita por sí solo una transacción']
    t = normalize(value)
    if re.search(r'declaracion\s+y\s+no\s+pago|declarad[ao]\s+sin\s+pago|pendiente\s+de\s+pago|pago\s+rechazado|sin\s+pago', t):
        return STATES['none'], ['Se observa declaración sin pago, pago pendiente o rechazado; revisar original']
    receipt = bool(re.search(r'comprobante\s+de\s+pago|recibo\s+de\s+pago',t))
    paid = bool(re.search(r'(?:estado|situacion|resultado)\s*(?:del\s+)?(?:pago)?\s*[:\-]?\s*pagad[oa]|pago\s+(?:realizado|exitoso|efectuado|confirmado)',t))
    transaction = bool(re.search(r'(?:folio|numero\s+(?:de\s+)?operacion|id\s+transaccion|codigo\s+de\s+pago)\s*[:#\-]?\s*[a-z0-9]{4,}',t))
    if receipt and paid and transaction and period:
        return STATES['paid'], ['Comprobante, estado, operación y período visibles documentalmente; sin verificación externa']
    if receipt or paid:
        missing=[name for name,ok in [('comprobante',receipt),('estado explícito',paid),('folio u operación',transaction),('período previsional',bool(period))] if not ok]
        return STATES['review'], ['Evidencia insuficiente: '+', '.join(missing)]
    return STATES['none'], ['Sin evidencia transaccional suficiente; no significa que exista impago']

def ocr_page(image: Image.Image, number: int) -> dict:
    cfg=get_settings()
    image=ImageOps.exif_transpose(image.convert('RGB'))
    image.thumbnail((3400,4400))
    try:
        osd=pytesseract.image_to_osd(image,timeout=8,output_type=pytesseract.Output.DICT)
        angle=int(osd.get('rotate',0))%360
        if angle: image=image.rotate(angle,expand=True)
    except (pytesseract.TesseractError,ValueError,RuntimeError):
        pass
    def read(img):
        try: return pytesseract.image_to_data(img,lang=cfg.ocr_lang,output_type=pytesseract.Output.DICT,timeout=45)
        except pytesseract.TesseractError: return pytesseract.image_to_data(img,lang='eng',output_type=pytesseract.Output.DICT,timeout=45)
    data=read(image)
    def metric(d):
        confidences=[float(c) for c in d['conf'] if float(c)>=0]
        return len(' '.join(w for w in d['text'] if w.strip())),sum(confidences)/len(confidences) if confidences else 0
    chars,avg=metric(data)
    if chars<45 or avg<43:
        alt=read(ImageOps.autocontrast(ImageOps.grayscale(image)).filter(ImageFilter.UnsharpMask(radius=1.1,percent=135,threshold=3)))
        other_len,other_avg=metric(alt)
        if other_len>chars*1.2 or (other_avg>avg+10 and other_len>=chars):
            data=alt;chars,avg=other_len,other_avg
    lines={}
    tokens=[]
    for i,word in enumerate(data['text']):
        if not word.strip(): continue
        key=(data['block_num'][i],data['par_num'][i],data['line_num'][i])
        lines.setdefault(key,[]).append(word.strip())
        if len(tokens)<100:
            tokens.append({'text':word.strip(),'bbox':[data['left'][i],data['top'][i],data['left'][i]+data['width'][i],data['top'][i]+data['height'][i]],'confidence':float(data['conf'][i])})
    return {'page':number,'mode':'ocr:tesseract','confidence':round(avg,1),'text':'\n'.join(' '.join(words) for words in lines.values()),'tokens':tokens}

def pdf_page(page: fitz.Page, number: int) -> dict:
    digital=page.get_text('text',sort=True)
    images=sum(max(0,r.get_area())/max(1,page.rect.get_area()) for item in page.get_images(full=True) for r in page.get_image_rects(item[0]))
    if len(digital.strip())>=70 and images<0.27:
        return {'page':number,'mode':'texto-digital','confidence':None,'text':digital,'tokens':[]}
    if page.rect.width*page.rect.height*4>30_000_000:
        raise ValueError('Página de dimensiones excesivas')
    pix=page.get_pixmap(matrix=fitz.Matrix(2,2),alpha=False,colorspace=fitz.csRGB)
    result=ocr_page(Image.frombytes('RGB',(pix.width,pix.height),pix.samples),number)
    if digital.strip() and images>=0.27 and result['text'].strip():
        result['text']=digital+'\n'+result['text']
        result['mode']='hibrido:texto+ocr'
    elif len(digital.strip())>len(result['text'].strip()):
        result.update(mode='texto-digital-parcial',confidence=None,text=digital)
    return result

def analyze_document(path: str | Path, declared_type: str='auto') -> dict:
    path=Path(path)
    pages=[]
    if path.suffix.lower()=='.pdf':
        with fitz.open(str(path)) as pdf:
            if pdf.is_encrypted or not 1<=len(pdf)<=get_settings().max_pdf_pages:
                raise ValueError('PDF cifrado, vacío o supera el máximo de páginas')
            pages=[pdf_page(page,i+1) for i,page in enumerate(pdf)]
    else:
        with Image.open(path) as image:
            if image.width*image.height>30_000_000: raise ValueError('Imagen demasiado grande')
            pages=[ocr_page(image,1)]
    full='\n'.join(p['text'] for p in pages)
    kind=detect_type(full)
    period=detect_period(full)
    if declared_type!='auto' and kind!=declared_type:
        state=STATES['wrong'];notes=['Tipo documental distinto del módulo elegido']
    else:
        state,notes=assess_payment(full,period,kind,len(full.strip())>=25)
    if state==STATES['paid'] and not any(assess_payment(p['text'],detect_period(p['text']),kind,True)[0]==STATES['paid'] for p in pages):
        state=STATES['review'];notes.append('La evidencia está dispersa entre páginas diferentes')
    low=[p['page'] for p in pages if ('ocr' in p['mode']) and p['confidence'] is not None and p['confidence']<55]
    if low:
        notes.append('Confianza OCR baja; revisar páginas '+', '.join(map(str,low)))
        if state==STATES['paid']:state=STATES['review']
    if any(len(p['text'].strip())<15 for p in pages):
        notes.append('Existen páginas con texto no recuperado')
        if state==STATES['paid']:state=STATES['review']
    evidence=[{'pagina':p['page'],'motor':p['mode'],'confianza_ocr':p['confidence'],'caracteres':len(p['text']),'extracto':p['text'][:500],'tokens_muestra':p['tokens']} for p in pages]
    fields=[{'campo':'periodo','valor':detect_period(p['text']),'pagina':p['page'],'motor':p['mode']} for p in pages if detect_period(p['text'])]
    for p in pages:
        for rut in find_ruts(p['text']):
            fields.append({'campo':'rut','valor':rut,'pagina':p['page'],'motor':p['mode']})
    return {'detected_type':kind,'payment_status':state,'page_count':len(pages),
            'extracted':{'periodo':period,'ruts_validos':find_ruts(full),
                         'paginas_procesadas':len(pages),'motores':sorted({p['mode'] for p in pages}),
                         'verificacion_externa':False,'fuentes_por_campo':fields[:350]},
            'evidence':evidence,'warnings':notes}
