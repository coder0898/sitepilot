"""communication hub tables"""
from alembic import op
import sqlalchemy as sa
revision = "0002_communication_hub"
down_revision = "0001_initial"
branch_labels = None
depends_on = None

def upgrade():
    op.create_table("vendor_categories", sa.Column("id", sa.Uuid(), primary_key=True), sa.Column("name", sa.Text(), nullable=False, unique=True), sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.text("true")), sa.Column("created_by", sa.Uuid(), sa.ForeignKey("users.id")), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")))
    op.create_table("vendor_contacts", sa.Column("id", sa.Uuid(), primary_key=True), sa.Column("vendor_id", sa.Uuid(), sa.ForeignKey("vendors.id", ondelete="CASCADE"), nullable=False), sa.Column("name", sa.Text(), nullable=False), sa.Column("designation", sa.Text()), sa.Column("phone", sa.Text(), nullable=False), sa.Column("whatsapp", sa.Text()), sa.Column("is_primary", sa.Boolean(), nullable=False, server_default=sa.text("false")), sa.Column("created_by", sa.Uuid(), sa.ForeignKey("users.id")), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")))
    op.create_table("project_vendors", sa.Column("id", sa.Uuid(), primary_key=True), sa.Column("project_id", sa.Uuid(), sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False), sa.Column("vendor_id", sa.Uuid(), sa.ForeignKey("vendors.id", ondelete="CASCADE"), nullable=False), sa.Column("created_by", sa.Uuid(), sa.ForeignKey("users.id")), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")), sa.UniqueConstraint("project_id", "vendor_id", name="uq_project_vendor"))
    op.create_table("communication_logs", sa.Column("id", sa.Uuid(), primary_key=True), sa.Column("vendor_id", sa.Uuid(), sa.ForeignKey("vendors.id", ondelete="CASCADE"), nullable=False), sa.Column("contact_id", sa.Uuid(), sa.ForeignKey("vendor_contacts.id", ondelete="SET NULL")), sa.Column("project_id", sa.Uuid(), sa.ForeignKey("projects.id", ondelete="CASCADE")), sa.Column("channel", sa.Text(), nullable=False), sa.Column("note", sa.Text(), nullable=False), sa.Column("created_by", sa.Uuid(), sa.ForeignKey("users.id"), nullable=False), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")))
    op.execute("insert into vendor_categories (id, name, created_at) select gen_random_uuid(), category, now() from vendors group by category on conflict (name) do nothing")
    op.execute("insert into vendor_contacts (id, vendor_id, name, phone, whatsapp, is_primary, created_at) select gen_random_uuid(), id, contact_person, phone, whatsapp, true, now() from vendors")

def downgrade():
    op.drop_table("communication_logs"); op.drop_table("project_vendors"); op.drop_table("vendor_contacts"); op.drop_table("vendor_categories")