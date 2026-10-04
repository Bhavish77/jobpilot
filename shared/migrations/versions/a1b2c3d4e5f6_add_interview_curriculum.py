"""add interview_curriculum to applications

Revision ID: a1b2c3d4e5f6
Revises: 86d77ffbae8d
Create Date: 2026-09-27

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'a1b2c3d4e5f6'
down_revision: Union[str, None] = '86d77ffbae8d'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('applications', sa.Column('interview_curriculum', sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column('applications', 'interview_curriculum')
