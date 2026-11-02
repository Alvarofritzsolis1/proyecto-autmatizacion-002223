import argparse
from getpass import getpass
from sqlalchemy import select
from .database import Base, engine, SessionLocal
from .models import Organization, User
from .security import hash_password

def main():
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest='command', required=True)
    sub.add_parser('init-db')
    admin = sub.add_parser('create-admin')
    admin.add_argument('--email', required=True)
    admin.add_argument('--organization', default='Mi organización')
    args = p.parse_args()
    if args.command == 'init-db':
        Base.metadata.create_all(bind=engine)
        return
    pw = getpass('Contraseña del administrador (12 caracteres mínimo): ')
    pw2 = getpass('Repetir contraseña: ')
    if pw != pw2:
        raise SystemExit('Las contraseñas no coinciden.')
    with SessionLocal.begin() as db:
        email = args.email.strip().lower()
        if db.scalar(select(User).where(User.email == email)):
            raise SystemExit('Ya existe el correo registrado.')
        org = Organization(name=args.organization)
        db.add(org)
        db.flush()
        db.add(User(org_id=org.id, email=email, password_hash=hash_password(pw), role='admin'))
    print('Administrador creado.')

if __name__ == '__main__':
    main()
