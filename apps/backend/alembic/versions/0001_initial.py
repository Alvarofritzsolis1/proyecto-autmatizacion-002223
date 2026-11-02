"""Crear tablas GALANT 2.0.
Revision ID: 0001_initial
Revises:
"""
from alembic import op
from app.database import Base
from app import models  # noqa
revision = '0001_initial'
down_revision = None
branch_labels = None
depends_on = None

def upgrade():
    Base.metadata.create_all(bind=op.get_bind())

def downgrade():
    Base.metadata.drop_all(bind=op.get_bind())
