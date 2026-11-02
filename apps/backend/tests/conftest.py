import os
import secrets
import tempfile
from pathlib import Path
import pytest
from fastapi.testclient import TestClient
root=Path(tempfile.mkdtemp(prefix='galant-ci-'))
os.environ['APP_SECRET']=secrets.token_hex(40)
os.environ['DATABASE_URL']='sqlite:///'+str(root/'test.db')
os.environ['DOCUMENT_DIR']=str(root/'documents')
os.environ['OCR_LANG']='eng'
from app.database import Base, SessionLocal, engine
from app.models import Organization,User
from app.security import hash_password
from app.main import app

@pytest.fixture(scope='session',autouse=True)
def tables():
    Base.metadata.create_all(engine)
    with SessionLocal.begin() as db:
        org=Organization(name='Prueba')
        db.add(org);db.flush()
        db.add(User(org_id=org.id,email='admin@example.cl',role='admin',
                    password_hash=hash_password('StrongTestPassword123!')))
    yield
    Base.metadata.drop_all(engine)

@pytest.fixture
def client(tables):
    with TestClient(app) as value:yield value
