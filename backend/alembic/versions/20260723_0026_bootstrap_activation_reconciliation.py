"""Add guarded Bootstrap activation reconciliation identity.

Revision ID: 20260723_0026
Revises: 20260722_0025
"""
from alembic import op
import sqlalchemy as sa


revision = "20260723_0026"
down_revision = "20260722_0025"
branch_labels = None
depends_on = None

TABLE = "wordpressbootstrapestablishmentaudit"
REASON = "post_activation_verifier_contract_defect_reconciled"
CONSTRAINT = "ck_wordpressbootstrapestablishmentaudit_reconciliation"
UNIQUE = "uq_wordpressbootstrapestablishmentaudit_reconciliation_handle"


def upgrade() -> None:
    columns = {item["name"] for item in sa.inspect(op.get_bind()).get_columns(TABLE)}
    if "reconciliation_reason" not in columns:
        op.add_column(TABLE, sa.Column("reconciliation_reason", sa.String(length=100), nullable=True))
        op.create_index(
            "ix_wordpressbootstrapestablishmentaudit_reconciliation_reason",
            TABLE,
            ["reconciliation_reason"],
        )
    if "reconciliation_handle_fingerprint" not in columns:
        op.add_column(
            TABLE,
            sa.Column("reconciliation_handle_fingerprint", sa.String(length=64), nullable=True),
        )
    if "reconciliation_binding_hash" not in columns:
        op.add_column(
            TABLE,
            sa.Column("reconciliation_binding_hash", sa.String(length=64), nullable=True),
        )
    if "reconciled_at" not in columns:
        op.add_column(TABLE, sa.Column("reconciled_at", sa.DateTime(), nullable=True))
    condition = (
        "(reconciliation_reason IS NULL AND reconciliation_handle_fingerprint IS NULL "
        "AND reconciliation_binding_hash IS NULL AND reconciled_at IS NULL) OR "
        f"(status = 'verified' AND reconciliation_reason = '{REASON}' "
        "AND reconciliation_handle_fingerprint IS NOT NULL "
        "AND reconciliation_binding_hash IS NOT NULL AND reconciled_at IS NOT NULL)"
    )
    if op.get_bind().dialect.name == "sqlite":
        with op.batch_alter_table(TABLE, recreate="always") as batch:
            batch.create_unique_constraint(UNIQUE, ["reconciliation_handle_fingerprint"])
            batch.create_check_constraint(CONSTRAINT, condition)
    else:
        op.create_unique_constraint(UNIQUE, TABLE, ["reconciliation_handle_fingerprint"])
        op.create_check_constraint(CONSTRAINT, TABLE, condition)


def downgrade() -> None:
    reconciled = op.get_bind().execute(
        sa.text(f"SELECT COUNT(*) FROM {TABLE} WHERE reconciliation_reason IS NOT NULL")
    ).scalar_one()
    if reconciled:
        raise RuntimeError(
            "Cannot downgrade while reconciled Bootstrap activation audits exist; "
            "preserve and migrate them first."
        )
    if op.get_bind().dialect.name == "sqlite":
        with op.batch_alter_table(TABLE, recreate="always") as batch:
            batch.drop_constraint(CONSTRAINT, type_="check")
            batch.drop_constraint(UNIQUE, type_="unique")
    else:
        op.drop_constraint(CONSTRAINT, TABLE, type_="check")
        op.drop_constraint(UNIQUE, TABLE, type_="unique")
    op.drop_index(
        "ix_wordpressbootstrapestablishmentaudit_reconciliation_reason",
        table_name=TABLE,
    )
    if op.get_bind().dialect.name == "sqlite":
        with op.batch_alter_table(TABLE, recreate="always") as batch:
            batch.drop_column("reconciled_at")
            batch.drop_column("reconciliation_binding_hash")
            batch.drop_column("reconciliation_handle_fingerprint")
            batch.drop_column("reconciliation_reason")
    else:
        op.drop_column(TABLE, "reconciled_at")
        op.drop_column(TABLE, "reconciliation_binding_hash")
        op.drop_column(TABLE, "reconciliation_handle_fingerprint")
        op.drop_column(TABLE, "reconciliation_reason")
