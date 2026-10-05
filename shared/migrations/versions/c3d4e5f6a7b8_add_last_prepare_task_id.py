"""add last_prepare_task_id to applications

Revision ID: c3d4e5f6a7b8
Revises: b2c3d4e5f6a7
Create Date: 2026-10-05

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'c3d4e5f6a7b8'
down_revision: Union[str, None] = 'b2c3d4e5f6a7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Nothing before this tracked which Celery task_id last ran for a
    # given application, so /prepare/status had no way to tell "still
    # genuinely running" apart from "the task died and nothing will ever
    # finish this" — it just reported "in_progress" forever either way.
    op.add_column('applications', sa.Column('last_prepare_task_id', sa.String(length=255), nullable=True))


def downgrade() -> None:
    op.drop_column('applications', 'last_prepare_task_id')
