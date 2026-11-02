import hashlib
import hmac
import secrets
from datetime import datetime, timedelta, timezone
import jwt
from argon2 import PasswordHasher
from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.orm import Session
from .config import get_settings
from .database import get_db
from .models import User

hasher = PasswordHasher()
SESSION_COOKIE = 'galant_session'
CSRF_COOKIE = 'galant_csrf'

def hash_password(password: str) -> str:
    if len(password) < 12:
        raise ValueError('La contraseña debe tener al menos 12 caracteres.')
    return hasher.hash(password)

def verify_password(password: str, password_hash: str) -> bool:
    try:
        return hasher.verify(password_hash, password)
    except Exception:
        return False

def issue_session(user: User) -> tuple[str, str]:
    cfg = get_settings()
    if cfg.app_secret == 'INSECURE_DEVELOPMENT_ONLY':
        raise RuntimeError('Configure APP_SECRET antes de habilitar autenticación.')
    jti = secrets.token_hex(24)
    payload = {'sub': user.id, 'org': user.org_id, 'jti': jti,
               'exp': datetime.now(timezone.utc) + timedelta(hours=cfg.session_hours),
               'iat': datetime.now(timezone.utc)}
    token = jwt.encode(payload, cfg.app_secret, algorithm='HS256')
    csrf = hmac.new(cfg.app_secret.encode(), jti.encode(), hashlib.sha256).hexdigest()
    return token, csrf

def current_user(request: Request, db: Session = Depends(get_db)) -> User:
    token = request.cookies.get(SESSION_COOKIE)
    if not token:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, 'Inicio de sesión requerido')
    try:
        payload = jwt.decode(token, get_settings().app_secret, algorithms=['HS256'])
        user = db.get(User, payload['sub'])
    except (jwt.PyJWTError, KeyError):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, 'Sesión inválida') from None
    if not user or not user.enabled or payload.get('org') != user.org_id:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, 'Sesión revocada')
    if request.method not in ('GET', 'HEAD', 'OPTIONS'):
        expected = hmac.new(get_settings().app_secret.encode(), payload['jti'].encode(), hashlib.sha256).hexdigest()
        header = request.headers.get('X-CSRF-Token', '')
        cookie = request.cookies.get(CSRF_COOKIE, '')
        if not (header and hmac.compare_digest(header, expected) and hmac.compare_digest(cookie, expected)):
            raise HTTPException(status.HTTP_403_FORBIDDEN, 'Protección CSRF: token incorrecto')
    return user

def can_write(user: User = Depends(current_user)) -> User:
    if user.role not in {'admin','analyst'}:
        raise HTTPException(403,'Permiso insuficiente')
    return user

def admin_only(user: User = Depends(current_user)) -> User:
    if user.role != 'admin':
        raise HTTPException(403,'Requiere rol administrador')
    return user
