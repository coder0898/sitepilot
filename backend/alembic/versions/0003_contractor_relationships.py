"""main contractor and subcontractor relationships"""
from alembic import op
import sqlalchemy as sa
revision = "0003_contractor_relationships"
down_revision = "0002_communication_hub"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "contractor_relationships",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("main_contractor_id", sa.Uuid(), sa.ForeignKey("vendors.id", ondelete="CASCADE"), nullable=False),
        sa.Column("subcontractor_id", sa.Uuid(), sa.ForeignKey("vendors.id", ondelete="CASCADE"), nullable=False),
        sa.Column("created_by", sa.Uuid(), sa.ForeignKey("users.id")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.CheckConstraint("main_contractor_id <> subcontractor_id", name="ck_contractor_not_self"),
        sa.UniqueConstraint("main_contractor_id", "subcontractor_id", name="uq_contractor_relationship"),
    )


def downgrade():
    op.drop_table("contractor_relationships")