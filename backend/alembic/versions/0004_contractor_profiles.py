"""contractor profiles and multiple categories"""
from alembic import op
import sqlalchemy as sa
revision = "0004_contractor_profiles"
down_revision = "0003_contractor_relationships"
branch_labels = None
depends_on = None

DEFAULT_CATEGORIES = ("Civil", "Electrical", "Plumbing", "HVAC", "Carpentry", "Painting", "Fire & Safety", "Flooring", "False Ceiling", "Interior Works", "Networking/CCTV", "Other")


def upgrade():
    op.add_column("vendors", sa.Column("status", sa.Text(), nullable=False, server_default="active"))
    op.add_column("vendors", sa.Column("email", sa.Text()))
    op.add_column("vendors", sa.Column("address", sa.Text()))
    op.add_column("vendors", sa.Column("gst_number", sa.Text()))
    op.create_table(
        "contractor_categories",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("vendor_id", sa.Uuid(), sa.ForeignKey("vendors.id", ondelete="CASCADE"), nullable=False),
        sa.Column("category_id", sa.Uuid(), sa.ForeignKey("vendor_categories.id", ondelete="CASCADE"), nullable=False),
        sa.UniqueConstraint("vendor_id", "category_id", name="uq_contractor_category"),
    )
    for name in DEFAULT_CATEGORIES:
        safe_name = name.replace("'", "''")
        op.execute(f"insert into vendor_categories (id, name, active, created_at) values (gen_random_uuid(), '{safe_name}', true, now()) on conflict (name) do nothing")
    op.execute("insert into contractor_categories (id, vendor_id, category_id) select gen_random_uuid(), v.id, c.id from vendors v join vendor_categories c on lower(c.name) = lower(v.category) on conflict (vendor_id, category_id) do nothing")


def downgrade():
    op.drop_table("contractor_categories")
    op.drop_column("vendors", "gst_number")
    op.drop_column("vendors", "address")
    op.drop_column("vendors", "email")
    op.drop_column("vendors", "status")