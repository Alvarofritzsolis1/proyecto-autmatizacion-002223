from pathlib import Path
import fitz
from app.ocr import detect_period,find_ruts,rut_is_valid,assess_payment,analyze_document,STATES

SAMPLE="""PREVIRED COMPROBANTE DE PAGO DE COTIZACIONES PREVISIONALES
Periodo de remuneracion: Octubre 2026
Estado: PAGADO
Folio: 123456789
Pago realizado correctamente.
Empresa y cotizaciones previsionales.
"""

def pdf(path:Path,text:str):
    with fitz.open() as doc:
        page=doc.new_page()
        for i,line in enumerate(text.splitlines()):
            page.insert_text((40,80+i*35),line,fontsize=11)
        doc.save(path)
    return path

def test_rut():
    assert rut_is_valid('12.345.678-5')
    assert not rut_is_valid('12.345.678-9')
    assert find_ruts('Rut 12.345.678-5')==['12.345.678-5']

def test_period():
    assert detect_period('Periodo de remuneracion: Octubre 2026')=='2026-10'
    assert detect_period('Periodo de cotizaciones: 02/2026')=='2026-02'
    assert detect_period('Fecha de pago 02/11/2026') is None

def test_payment_evidence():
    assert assess_payment('Monto pagado 30.000',None,'cotizaciones',True)[0]!=STATES['paid']
    assert assess_payment(SAMPLE,'2026-10','cotizaciones',True)[0]==STATES['paid']
    assert assess_payment(SAMPLE+' DECLARACION Y NO PAGO','2026-10','cotizaciones',True)[0]==STATES['none']
    assert assess_payment(SAMPLE,'2026-10','f30_1',True)[0]==STATES['review']

def test_native_pdf(tmp_path):
    result=analyze_document(pdf(tmp_path/'ok.pdf',SAMPLE),'cotizaciones')
    assert result['detected_type']=='cotizaciones'
    assert result['payment_status']==STATES['paid']
    assert result['extracted']['periodo']=='2026-10'
    assert result['extracted']['verificacion_externa'] is False
    assert result['evidence'][0]['pagina']==1

def test_module_separation(tmp_path):
    doc=pdf(tmp_path/'f301.pdf','F30-1 CERTIFICADO DE CUMPLIMIENTO DE OBLIGACIONES LABORALES. '*4)
    result=analyze_document(doc,'f30_1')
    assert result['detected_type']=='f30_1'
    assert result['payment_status']==STATES['review']

def test_wrong_document(tmp_path):
    result=analyze_document(pdf(tmp_path/'misfile.pdf',SAMPLE),'f30_1')
    assert result['payment_status']==STATES['wrong']
