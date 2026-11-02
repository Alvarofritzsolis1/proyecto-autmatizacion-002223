"""Worker aislado; obtiene trabajos en PostgreSQL de forma transaccional."""
import logging
import signal
import time
from datetime import timedelta
from sqlalchemy import or_,select
from .config import get_settings
from .database import SessionLocal
from .models import Document,now
from .ocr import analyze_document
logging.basicConfig(level=logging.INFO)
logger=logging.getLogger('galant.worker')
stopping=False

def stop(*_):
    global stopping
    stopping=True

def process_one() -> bool:
    with SessionLocal.begin() as db:
        query=(select(Document)
               .where(or_(Document.status=='queued',(Document.status=='processing')&(Document.updated_at<now()-timedelta(minutes=30))))
               .order_by(Document.created_at).with_for_update(skip_locked=True).limit(1))
        doc=db.scalar(query)
        if not doc:return False
        doc.status='processing';doc.updated_at=now()
        identifier,path,kind=doc.id,doc.storage_path,doc.declared_type
    try:
        result=analyze_document(path,kind)
        with SessionLocal.begin() as db:
            doc=db.get(Document,identifier)
            if doc:
                doc.detected_type=result['detected_type'];doc.payment_status=result['payment_status']
                doc.page_count=result['page_count'];doc.extracted=result['extracted']
                doc.evidence=result['evidence'];doc.warnings=result['warnings'];doc.status='complete';doc.updated_at=now()
        logger.info('Processed document %s',identifier)
    except Exception as exc:
        logger.exception('Document processing failed %s',identifier)
        with SessionLocal.begin() as db:
            doc=db.get(Document,identifier)
            if doc:
                doc.status='error';doc.error_message=type(exc).__name__+': requiere revisión técnica';doc.updated_at=now()
    return True

def main():
    signal.signal(signal.SIGTERM,stop)
    signal.signal(signal.SIGINT,stop)
    while not stopping:
        if not process_one():time.sleep(get_settings().worker_poll_seconds)

if __name__=='__main__':
    main()
