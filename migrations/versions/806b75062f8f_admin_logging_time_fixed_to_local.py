"""admin logging time fixed to local

Revision ID: 806b75062f8f
Revises: 
Create Date: 2025-06-01 22:04:26.290612

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.sql import table, column
from sqlalchemy import DateTime
import datetime

# define a table reference
logs_table = table('logs',
    column('timestamp', DateTime)
)

def upgrade():
    # Set a default timestamp for existing NULLs
    op.execute(
        logs_table.update()
        .where(logs_table.c.timestamp == None)
        .values(timestamp=datetime.datetime.utcnow())
    )

    # Now enforce NOT NULL
    with op.batch_alter_table('logs') as batch_op:
        batch_op.alter_column('timestamp', nullable=False)

def downgrade():
    with op.batch_alter_table('logs') as batch_op:
        batch_op.alter_column('timestamp', nullable=True)
