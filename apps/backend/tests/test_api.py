import fitz
from app.worker import process_one

def sample_pdf():
    doc=fitz.open()
    page=doc.new_page()
    for i,line in enumerate([
        'PREVIRED COMPROBANTE DE PAGO DE COTIZACIONES PREVISIONALES',
        'Periodo de remuneracion: Octubre 2026',
        'Estado: PAGADO','Folio: 123456789','Pago realizado correctamente',
        'Empresa y cotizaciones previsionales']):
        page.insert_text((40,70+i*30),line)
    out=doc.tobytes();doc.close()
    return out

def test_requires_login(client):
    assert client.get('/api/v1/dashboard').status_code==401

def test_full_flow(client):
    r=client.post('/api/v1/auth/login',json={'email':'admin@example.cl','password':'StrongTestPassword123!'})
    assert r.status_code==200
    csrf=client.cookies.get('galant_csrf')
    assert client.post('/api/v1/contractors',json={'name':'Empresa de prueba'}).status_code==403
    headers={'X-CSRF-Token':csrf}
    contractor=client.post('/api/v1/contractors',json={'name':'Empresa de prueba'},headers=headers)
    assert contractor.status_code==201
    uploaded=client.post('/api/v1/documents',files={'file':('comprobante.pdf',sample_pdf(),'application/pdf')},
      data={'doc_type':'cotizaciones','contractor_id':contractor.json()['id']},headers=headers)
    assert uploaded.status_code==202,uploaded.text
    identifier=uploaded.json()['id']
    assert process_one() is True
    result=client.get('/api/v1/documents/'+identifier)
    assert result.status_code==200
    assert result.json()['status']=='complete'
    assert result.json()['payment_status']=='Pago acreditado documentalmente'
    assert client.get('/api/v1/documents/'+identifier+'/file').status_code==200
    assert client.get('/api/v1/documents/'+identifier+'/report').status_code==200
    assert client.get('/api/v1/dashboard').json()['acreditados']>=1
    assert client.post('/api/v1/auth/logout',headers=headers).status_code==200
    assert client.get('/api/v1/dashboard').status_code==401

def test_reject_malicious_extension(client):
    client.post('/api/v1/auth/login',json={'email':'admin@example.cl','password':'StrongTestPassword123!'})
    headers={'X-CSRF-Token':client.cookies.get('galant_csrf')}
    bad=client.post('/api/v1/documents',files={'file':('virus.exe',b'exe','application/octet-stream')},headers=headers)
    assert bad.status_code==415
    invalid=client.post('/api/v1/documents',files={'file':('fake.pdf',b'not-pdf','application/pdf')},headers=headers)
    assert invalid.status_code==415
