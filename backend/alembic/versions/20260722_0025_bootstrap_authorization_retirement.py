"""Add guarded bootstrap authorization retirement.

Revision ID: 20260722_0025
Revises: 20260720_0024
"""
from alembic import op
import sqlalchemy as sa

revision = "20260722_0025"
down_revision = "20260720_0024"
branch_labels = None
depends_on = None

TABLE = "wordpressbootstrapestablishmentaudit"
STATUS_CONSTRAINT = "ck_wordpressbootstrapestablishmentaudit_status"
MODE_CONSTRAINT = "ck_wordpressbootstrapestablishmentaudit_authorization_mode"
REASON_CONSTRAINT = "ck_wordpressbootstrapestablishmentaudit_retirement_reason"
OLD_STATUSES = (
    "'awaiting_manual_bootstrap_installation','manual_installation_inventory_verified',"
    "'activation_pending_checksum_verification','verified','manual_installation_mismatch',"
    "'manual_activation_detected','installation_partial','checksum_mismatch',"
    "'checksum_unavailable','verification_failed','recovery_required'"
)
NEW_STATUSES = OLD_STATUSES.replace("'verified'", "'verified','authorization_retired'")


def _replace_status_constraint(statuses: str) -> None:
    dialect = op.get_bind().dialect.name
    if dialect == "sqlite":
        with op.batch_alter_table(TABLE, recreate="always") as batch:
            batch.drop_constraint(STATUS_CONSTRAINT, type_="check")
            batch.create_check_constraint(STATUS_CONSTRAINT, f"status IN ({statuses})")
    else:
        op.drop_constraint(STATUS_CONSTRAINT, TABLE, type_="check")
        op.create_check_constraint(STATUS_CONSTRAINT, TABLE, f"status IN ({statuses})")


def upgrade() -> None:
    columns = {item["name"] for item in sa.inspect(op.get_bind()).get_columns(TABLE)}
    if "authorization_mode" not in columns:
        op.add_column(
            TABLE,
            sa.Column("authorization_mode", sa.String(length=64), nullable=False, server_default="manual_upload"),
        )
        op.create_index("ix_wordpressbootstrapestablishmentaudit_authorization_mode", TABLE, ["authorization_mode"])
    if "retirement_reason" not in columns:
        op.add_column(TABLE, sa.Column("retirement_reason", sa.String(length=100), nullable=True))
        op.create_index("ix_wordpressbootstrapestablishmentaudit_retirement_reason", TABLE, ["retirement_reason"])
    _replace_status_constraint(NEW_STATUSES)
    if op.get_bind().dialect.name == "sqlite":
        with op.batch_alter_table(TABLE, recreate="always") as batch:
            batch.create_check_constraint(MODE_CONSTRAINT, "authorization_mode IN ('manual_upload','existing_exact_inactive_bootstrap')")
            batch.create_check_constraint(REASON_CONSTRAINT, "(status = 'authorization_retired' AND retirement_reason = 'manual_install_verification_genuine_transport_drift') OR (status != 'authorization_retired' AND retirement_reason IS NULL)")
    else:
        op.create_check_constraint(MODE_CONSTRAINT, TABLE, "authorization_mode IN ('manual_upload','existing_exact_inactive_bootstrap')")
        op.create_check_constraint(REASON_CONSTRAINT, TABLE, "(status = 'authorization_retired' AND retirement_reason = 'manual_install_verification_genuine_transport_drift') OR (status != 'authorization_retired' AND retirement_reason IS NULL)")


def downgrade() -> None:
    retired = op.get_bind().execute(
        sa.text(f"SELECT COUNT(*) FROM {TABLE} WHERE status = 'authorization_retired'")
    ).scalar_one()
    if retired:
        raise RuntimeError(
            "Cannot downgrade while authorization_retired bootstrap audits exist; preserve and migrate them first."
        )
    if op.get_bind().dialect.name == "sqlite":
        with op.batch_alter_table(TABLE, recreate="always") as batch:
            batch.drop_constraint(REASON_CONSTRAINT, type_="check")
            batch.drop_constraint(MODE_CONSTRAINT, type_="check")
    else:
        op.drop_constraint(REASON_CONSTRAINT, TABLE, type_="check")
        op.drop_constraint(MODE_CONSTRAINT, TABLE, type_="check")
    _replace_status_constraint(OLD_STATUSES)
    columns = {item["name"] for item in sa.inspect(op.get_bind()).get_columns(TABLE)}
    if "retirement_reason" in columns:
        op.drop_index("ix_wordpressbootstrapestablishmentaudit_retirement_reason", table_name=TABLE)
        op.drop_column(TABLE, "retirement_reason")
    if "authorization_mode" in columns:
        op.drop_index("ix_wordpressbootstrapestablishmentaudit_authorization_mode", table_name=TABLE)
        op.drop_column(TABLE, "authorization_mode")
