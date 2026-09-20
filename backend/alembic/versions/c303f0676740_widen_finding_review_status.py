"""widen finding.review_status

The column was String(16). `review_finding` writes "changes_requested" on
rejection, which is 17 characters, so every rejection raised
StringDataRightTruncation and rolled the transaction back. The approval path
fit, so the review gate passed its tests while being able to approve and never
able to reject.

Revision ID: c303f0676740
Revises: a31fb4cb8e6c
Create Date: 2026-09-19 18:10:00.000000
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = 'c303f0676740'
down_revision = 'a31fb4cb8e6c'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column(
        'finding',
        'review_status',
        existing_type=sa.String(length=16),
        type_=sa.String(length=24),
        existing_nullable=False,
    )


def downgrade() -> None:
    # Narrowing back would truncate any row that was actually rejected, so the
    # rows have to be moved to a value that fits before the type changes.
    op.execute(
        "UPDATE finding SET review_status = 'changes_req' "
        "WHERE review_status = 'changes_requested'"
    )
    op.alter_column(
        'finding',
        'review_status',
        existing_type=sa.String(length=24),
        type_=sa.String(length=16),
        existing_nullable=False,
    )
