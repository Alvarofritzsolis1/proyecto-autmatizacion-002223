"""GALANT 2.0 API. Contratos separados, sesiones, evidencia documental y OCR asíncrono."""
from __future__ import annotations
import hashlib
import io
import os
import re
import time
from collections import defaultdict, deque
from pathlib import Path
from uuid import uuid4
import fitz
from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, Response, UploadFile
from fastapi.responses import FileResponse, StreamingResponse
from openpyxl import Workbook
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session
from .config import get_settings
from .database import get_db
from .models import AuditEvent, Contractor, Document, User
from .schemas import ContractorCreate, ContractorOut, DocumentOut, Login, Profile
from .security import CSRF_COOKIE, SESSION_COOKIE, can_write, current_user, issue_session, verify_password

app=FastAPI(title='GALANT 2.0 API',version='0.1.0',docs_url=None,redoc_url=None)
PREFIX='/api/v1'
attempts: dict[str,deque] = defaultdict(deque)

def audit(db: Session, user: User, action: str, resource: str | None=None):
    db.add(AuditEvent(org_id=user.org_id,user_id=user.id,action=action,resource_id=resource))

def find_doc(db: Session,user: User, doc_id: str) -> Document:
    doc=db.scalar(select(Document).where(Document.id==doc_id,Document.org_id==user.org_id))
    if not doc:raise HTTPException(404,'Documento no encontrado')
    return doc

@app.get(PREFIX+'/health')
def health(db: Session=Depends(get_db)):
    try:db.execute(text('SELECT 1'))
    except Exception:raise HTTPException(503,'Base de datos indisponible') from None
    return {'status':'ok','service':'galant-api'}

@app.post(PREFIX+'/auth/login',response_model=Profile)
def login(data: Login,request:Request,response:Response,db:Session=Depends(get_db)):
    remote=request.client.host if request.client else 'unknown'
    key=remote+':'+data.email.strip().lower()
    queue=attempts[key]
    t=time.monotonic()
    while queue and t-queue[0]>600:queue.popleft()
    if len(queue)>=8:raise HTTPException(429,'Demasiados intentos')
    user=db.scalar(select(User).where(User.email==data.email.strip().lower()))
    if not user or not user.enabled or not verify_password(data.password,user.password_hash):
        queue.append(t);raise HTTPException(401,'Credenciales incorrectas')
    queue.clear()
    token,csrf=issue_session(user)
    cfg=get_settings()
    response.set_cookie(SESSION_COOKIE,token,httponly=True,secure=cfg.cookie_secure,samesite='strict',max_age=cfg.session_hours*3600,path='/')
    response.set_cookie(CSRF_COOKIE,csrf,httponly=False,secure=cfg.cookie_secure,samesite='strict',max_age=cfg.session_hours*3600,path='/')
    audit(db,user,'login');db.commit()
    return user

@app.post(PREFIX+'/auth/logout')
def logout(response:Response,user:User=Depends(current_user),db:Session=Depends(get_db)):
    audit(db,user,'logout');db.commit()
    response.delete_cookie(SESSION_COOKIE,path='/');response.delete_cookie(CSRF_COOKIE,path='/')
    return {'ok':True}

@app.get(PREFIX+'/auth/me',response_model=Profile)
def me(user:User=Depends(current_user)):
    return user

@app.get(PREFIX+'/dashboard')
def dashboard(user:User=Depends(current_user),db:Session=Depends(get_db)):
    rows=db.execute(select(Document.status,Document.payment_status,func.count(Document.id)).where(Document.org_id==user.org_id).group_by(Document.status,Document.payment_status)).all()
    return {
        'documentos':sum(n for _,_,n in rows),
        'procesados':sum(n for s,_,n in rows if s=='complete'),
        'en_cola':sum(n for s,_,n in rows if s in ('queued','processing')),
        'acreditados':sum(n for s,p,n in rows if s=='complete' and p=='Pago acreditado documentalmente'),
        'revision':sum(n for s,p,n in rows if s=='complete' and p=='Pendiente de revisión'),
        'errores':sum(n for s,_,n in rows if s=='error'),
        'contratistas':db.scalar(select(func.count(Contractor.id)).where(Contractor.org_id==user.org_id)) or 0,
    }

@app.get(PREFIX+'/contractors',response_model=list[ContractorOut])
def list_contractors(user:User=Depends(current_user),db:Session=Depends(get_db)):
    return db.scalars(select(Contractor).where(Contractor.org_id==user.org_id).order_by(Contractor.created_at.desc()).limit(500)).all()

@app.post(PREFIX+'/contractors',response_model=ContractorOut,status_code=201)
def create_contractor(data:ContractorCreate,user:User=Depends(can_write),db:Session=Depends(get_db)):
    contractor=Contractor(org_id=user.org_id,name=data.name.strip(),rut=data.rut)
    db.add(contractor);db.flush()
    audit(db,user,'contractor.created',contractor.id);db.commit();db.refresh(contractor)
    return contractor

@app.get(PREFIX+'/documents',response_model=list[DocumentOut])
def list_documents(doc_type:str|None=None,user:User=Depends(current_user),db:Session=Depends(get_db)):
    q=select(Document).where(Document.org_id==user.org_id)
    if doc_type in {'cotizaciones','f30_1','independientes'}:
        q=q.where((Document.declared_type==doc_type)|(Document.detected_type==doc_type))
    return db.scalars(q.order_by(Document.created_at.desc()).limit(200)).all()

@app.post(PREFIX+'/documents',response_model=DocumentOut,status_code=202)
async def upload_document(file:UploadFile=File(...),doc_type:str=Form('auto'),
                          contractor_id:str|None=Form(None),user:User=Depends(can_write),
                          db:Session=Depends(get_db)):
    if doc_type not in {'auto','cotizaciones','f30_1','independientes'}:
        raise HTTPException(422,'Tipo documental no admitido')
    if contractor_id and not db.scalar(select(Contractor.id).where(Contractor.org_id==user.org_id,Contractor.id==contractor_id)):
        raise HTTPException(404,'Contratista no encontrado')
    cfg=get_settings()
    original=re.sub(r'[^\w .()\-]','_',Path(file.filename or 'documento.pdf').name)[:255]
    ext=Path(original).suffix.lower()
    if ext not in {'.pdf','.png','.jpg','.jpeg','.tif','.tiff'}:
        raise HTTPException(415,'Solo PDF e imágenes admitidos')
    private_dir=cfg.document_dir/user.org_id
    private_dir.mkdir(mode=0o700,parents=True,exist_ok=True)
    identifier=str(uuid4());path=private_dir/(identifier+ext)
    digest=hashlib.sha256();total=0;header=b''
    try:
        with path.open('xb') as out:
            os.chmod(path,0o600)
            while chunk:=await file.read(1024*1024):
                total+=len(chunk)
                if total>cfg.max_upload_mb*1024*1024:raise HTTPException(413,'Archivo demasiado grande')
                digest.update(chunk)
                if len(header)<32:header+=chunk[:32-len(header)]
                out.write(chunk)
        if ext=='.pdf':
            if not header.startswith(b'%PDF-'):raise HTTPException(415,'Cabecera PDF inválida')
            try:
                with fitz.open(str(path)) as pdf:
                    if pdf.is_encrypted:raise HTTPException(422,'PDF cifrado')
                    if not 1<=len(pdf)<=cfg.max_pdf_pages:raise HTTPException(422,'Número de páginas no permitido')
            except (fitz.FileDataError,fitz.FileNotFoundError):
                raise HTTPException(422,'PDF corrupto') from None
        else:
            from PIL import Image,UnidentifiedImageError
            try:
                with Image.open(path) as img:
                    img.verify()
                with Image.open(path) as img:
                    if img.width*img.height>30_000_000:raise HTTPException(413,'Resolución excesiva')
            except (UnidentifiedImageError,OSError):
                raise HTTPException(422,'Imagen inválida') from None
        duplicate=db.scalar(select(Document).where(Document.org_id==user.org_id,Document.sha256==digest.hexdigest()).order_by(Document.created_at.desc()))
        if duplicate:
            path.unlink(missing_ok=True)
            return duplicate
        doc=Document(id=identifier,org_id=user.org_id,user_id=user.id,contractor_id=contractor_id,original_name=original,
                     mime_type='application/pdf' if ext=='.pdf' else 'image/'+ext.lstrip('.'),sha256=digest.hexdigest(),
                     storage_path=str(path),declared_type=doc_type,status='queued',extracted={},evidence=[],warnings=[])
        db.add(doc);audit(db,user,'document.uploaded',identifier);db.commit();db.refresh(doc)
        return doc
    except BaseException:
        path.unlink(missing_ok=True)
        raise
    finally:
        await file.close()

@app.get(PREFIX+'/documents/{doc_id}',response_model=DocumentOut)
def get_document(doc_id:str,user:User=Depends(current_user),db:Session=Depends(get_db)):
    return find_doc(db,user,doc_id)

@app.get(PREFIX+'/documents/{doc_id}/file')
def view_document(doc_id:str,user:User=Depends(current_user),db:Session=Depends(get_db)):
    doc=find_doc(db,user,doc_id)
    path=Path(doc.storage_path)
    if not path.is_file():raise HTTPException(404,'Archivo no disponible')
    return FileResponse(path,media_type=doc.mime_type,filename=doc.original_name,content_disposition_type='inline',
                        headers={'Cache-Control':'no-store','X-Content-Type-Options':'nosniff','Content-Security-Policy':'sandbox'})

@app.post(PREFIX+'/documents/{doc_id}/retry',response_model=DocumentOut)
def retry(doc_id:str,user:User=Depends(can_write),db:Session=Depends(get_db)):
    doc=find_doc(db,user,doc_id)
    if doc.status not in {'error','complete'}:raise HTTPException(409,'Documento en proceso')
    doc.status='queued';doc.error_message=None
    audit(db,user,'document.reprocess_requested',doc_id);db.commit();db.refresh(doc)
    return doc

def safe_excel(value:object)->str:
    val=str(value) if value is not None else ''
    return "'"+val if val.startswith(('=','+','-','@','\t','\r')) else val

@app.get(PREFIX+'/documents/{doc_id}/report')
def report(doc_id:str,user:User=Depends(current_user),db:Session=Depends(get_db)):
    doc=find_doc(db,user,doc_id)
    if doc.status!='complete':raise HTTPException(409,'Análisis no finalizado')
    wb=Workbook();sh=wb.active;sh.title='Resultado'
    for k,v in [('Archivo',doc.original_name),('Tipo',doc.detected_type),('Estado documental',doc.payment_status),
                ('Páginas',doc.page_count),('Período',doc.extracted.get('periodo')),
                ('RUT válidos',', '.join(doc.extracted.get('ruts_validos',[]))),('Verificación externa','NO')]:
        sh.append([k,safe_excel(v)])
    evidence=wb.create_sheet('Evidencias');evidence.append(['Página','Motor','Confianza OCR','Texto'])
    for item in doc.evidence:evidence.append([item.get('pagina'),safe_excel(item.get('motor')),item.get('confianza_ocr'),safe_excel(item.get('extracto'))])
    alerts=wb.create_sheet('Observaciones');alerts.append(['Hallazgo'])
    for warning in doc.warnings:alerts.append([safe_excel(warning)])
    output=io.BytesIO();wb.save(output);output.seek(0)
    return StreamingResponse(output,media_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
                             headers={'Content-Disposition':f'attachment; filename="galant-{doc.id}.xlsx"','Cache-Control':'no-store'})
