"""phase 1 vendor hierarchy, category taxonomy, and status history"""

import sqlalchemy as sa
from alembic import op

revision = "0014_vendor_category_phase1"
down_revision = "0013_notification_delivery"
branch_labels = None
depends_on = None


def upgrade():
    # Material / Service taxonomy with a strict two-level hierarchy.
    op.add_column("vendor_categories", sa.Column("category_type", sa.Text(), nullable=False, server_default="service"))
    op.add_column("vendor_categories", sa.Column("parent_id", sa.Uuid()))
    op.add_column("vendor_categories", sa.Column("description", sa.Text()))
    op.create_foreign_key("fk_vendor_category_parent", "vendor_categories", "vendor_categories", ["parent_id"], ["id"], ondelete="RESTRICT")
    op.create_check_constraint("ck_vendor_category_type", "vendor_categories", "category_type in ('material', 'service')")
    op.create_check_constraint("ck_vendor_category_not_self_parent", "vendor_categories", "parent_id IS NULL OR parent_id <> id")
    op.create_index("ix_vendor_categories_parent_id", "vendor_categories", ["parent_id"])

    # Resolved sub-vendors use parent_vendor_id. Legacy independents are never guessed.
    op.add_column("vendors", sa.Column("parent_vendor_id", sa.Uuid()))
    op.add_column("vendors", sa.Column("migration_status", sa.Text(), nullable=False, server_default="ready"))
    op.create_foreign_key("fk_vendor_parent_vendor", "vendors", "vendors", ["parent_vendor_id"], ["id"], ondelete="RESTRICT")

    op.create_table(
        "vendor_parent_migration_candidates",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("vendor_id", sa.Uuid(), sa.ForeignKey("vendors.id", ondelete="CASCADE"), nullable=False),
        sa.Column("candidate_parent_vendor_id", sa.Uuid(), sa.ForeignKey("vendors.id", ondelete="CASCADE")),
        sa.Column("original_engagement_type", sa.Text(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("resolved_at", sa.DateTime(timezone=True)),
        sa.Column("resolved_by", sa.Uuid(), sa.ForeignKey("users.id")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.UniqueConstraint("vendor_id", "candidate_parent_vendor_id", name="uq_vendor_parent_migration_candidate"),
    )

    # Existing explicitly-linked subcontractors with exactly one parent are safe to backfill.
    op.execute("""
        update vendors v
        set parent_vendor_id = links.main_contractor_id,
            engagement_type = 'sub_vendor',
            migration_status = 'ready'
        from (
            select subcontractor_id, (array_agg(main_contractor_id order by main_contractor_id))[1] as main_contractor_id
            from contractor_relationships
            group by subcontractor_id
            having count(distinct main_contractor_id) = 1
        ) links
        where v.id = links.subcontractor_id
          and v.engagement_type = 'exclusive_subcontractor'
    """)

    # Preserve every possible parent for records that require a management decision.
    op.execute("""
        insert into vendor_parent_migration_candidates (id, vendor_id, candidate_parent_vendor_id, original_engagement_type, reason)
        select gen_random_uuid(), v.id, r.main_contractor_id, v.engagement_type,
               case when v.engagement_type = 'independent'
                    then 'Legacy independent subcontractor requires an approved parent.'
                    else 'Multiple or ambiguous legacy parent relationships require review.' end
        from vendors v
        left join contractor_relationships r on r.subcontractor_id = v.id
        where v.engagement_type = 'independent'
           or (v.engagement_type = 'exclusive_subcontractor' and v.parent_vendor_id is null)
        on conflict (vendor_id, candidate_parent_vendor_id) do nothing
    """)
    op.execute("""
        update vendors
        set engagement_type = 'migration_pending', migration_status = 'parent_required', parent_vendor_id = null
        where engagement_type = 'independent'
           or (engagement_type = 'exclusive_subcontractor' and parent_vendor_id is null)
    """)
    op.execute("delete from contractor_relationships where subcontractor_id in (select id from vendors where migration_status = 'parent_required')")
    op.execute("""
        delete from contractor_relationships duplicate
        using contractor_relationships keeper
        where duplicate.subcontractor_id = keeper.subcontractor_id
          and (duplicate.created_at, duplicate.id) > (keeper.created_at, keeper.id)
    """)
    op.create_unique_constraint("uq_contractor_relationship_subcontractor", "contractor_relationships", ["subcontractor_id"])

    op.create_check_constraint("ck_vendor_engagement_type", "vendors", "engagement_type in ('main', 'sub_vendor', 'migration_pending')")
    op.create_check_constraint("ck_vendor_sub_vendor_parent", "vendors", "engagement_type != 'sub_vendor' OR parent_vendor_id IS NOT NULL")
    op.create_check_constraint("ck_vendor_main_without_parent", "vendors", "engagement_type != 'main' OR parent_vendor_id IS NULL")
    op.create_check_constraint("ck_vendor_migration_status", "vendors", "migration_status in ('ready', 'parent_required')")
    op.create_check_constraint("ck_vendor_pending_state", "vendors", "engagement_type != 'migration_pending' OR (migration_status = 'parent_required' AND parent_vendor_id IS NULL)")
    op.create_check_constraint("ck_vendor_ready_state", "vendors", "engagement_type = 'migration_pending' OR migration_status = 'ready'")
    op.create_index("ix_vendors_parent_vendor_id", "vendors", ["parent_vendor_id"])
    op.create_index("ix_vendors_migration_status", "vendors", ["migration_status"])

    # Keep the legacy category text while adding structured references to both
    # template tasks and generated project tasks. Template tasks must be
    # migrated first because application startup seeds them immediately after
    # Alembic reaches head.
    op.add_column("execution_template_tasks", sa.Column("category_id", sa.Uuid()))
    op.add_column("execution_template_tasks", sa.Column("subcategory_id", sa.Uuid()))
    op.create_foreign_key(
        "fk_execution_template_task_category",
        "execution_template_tasks",
        "vendor_categories",
        ["category_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_foreign_key(
        "fk_execution_template_task_subcategory",
        "execution_template_tasks",
        "vendor_categories",
        ["subcategory_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.execute("""
        update execution_template_tasks t
        set category_id = c.id
        from vendor_categories c
        where lower(btrim(t.category)) = lower(btrim(c.name))
          and c.parent_id is null
    """)
    op.create_index("ix_execution_template_tasks_category_id", "execution_template_tasks", ["category_id"])
    op.create_index("ix_execution_template_tasks_subcategory_id", "execution_template_tasks", ["subcategory_id"])

    op.add_column("execution_tasks", sa.Column("category_id", sa.Uuid()))
    op.add_column("execution_tasks", sa.Column("subcategory_id", sa.Uuid()))
    op.create_foreign_key("fk_execution_task_category", "execution_tasks", "vendor_categories", ["category_id"], ["id"], ondelete="SET NULL")
    op.create_foreign_key("fk_execution_task_subcategory", "execution_tasks", "vendor_categories", ["subcategory_id"], ["id"], ondelete="SET NULL")
    op.execute("""
        update execution_tasks t
        set category_id = c.id
        from vendor_categories c
        where lower(btrim(t.category)) = lower(btrim(c.name))
          and c.parent_id is null
    """)
    op.create_index("ix_execution_tasks_category_id", "execution_tasks", ["category_id"])
    op.create_index("ix_execution_tasks_subcategory_id", "execution_tasks", ["subcategory_id"])

    op.create_table(
        "execution_task_status_history",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("task_id", sa.Uuid(), sa.ForeignKey("execution_tasks.id", ondelete="CASCADE"), nullable=False),
        sa.Column("from_status", sa.Text()),
        sa.Column("to_status", sa.Text(), nullable=False),
        sa.Column("reason", sa.Text()),
        sa.Column("changed_by", sa.Uuid(), sa.ForeignKey("users.id")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("ix_execution_task_status_history_task", "execution_task_status_history", ["task_id", "created_at"])
    op.execute("""
        insert into execution_task_status_history (id, task_id, from_status, to_status, reason, changed_by, created_at)
        select gen_random_uuid(), id, null, status, 'Backfilled current status during Phase 1 migration', created_by, coalesce(created_at, now())
        from execution_tasks
    """)

    op.create_table(
        "vendor_status_history",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("vendor_id", sa.Uuid(), sa.ForeignKey("vendors.id", ondelete="CASCADE"), nullable=False),
        sa.Column("from_status", sa.Text()),
        sa.Column("to_status", sa.Text(), nullable=False),
        sa.Column("reason", sa.Text()),
        sa.Column("changed_by", sa.Uuid(), sa.ForeignKey("users.id")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("ix_vendor_status_history_vendor", "vendor_status_history", ["vendor_id", "created_at"])
    op.execute("""
        insert into vendor_status_history (id, vendor_id, from_status, to_status, reason, changed_by, created_at)
        select gen_random_uuid(), id, null, status, 'Backfilled current status during Phase 1 migration', created_by, coalesce(created_at, now())
        from vendors
    """)


def downgrade():
    op.drop_index("ix_vendor_status_history_vendor", table_name="vendor_status_history")
    op.drop_table("vendor_status_history")
    op.drop_index("ix_execution_task_status_history_task", table_name="execution_task_status_history")
    op.drop_table("execution_task_status_history")

    op.drop_index("ix_execution_tasks_subcategory_id", table_name="execution_tasks")
    op.drop_index("ix_execution_tasks_category_id", table_name="execution_tasks")
    op.drop_constraint("fk_execution_task_subcategory", "execution_tasks", type_="foreignkey")
    op.drop_constraint("fk_execution_task_category", "execution_tasks", type_="foreignkey")
    op.drop_column("execution_tasks", "subcategory_id")
    op.drop_column("execution_tasks", "category_id")

    op.drop_index("ix_execution_template_tasks_subcategory_id", table_name="execution_template_tasks")
    op.drop_index("ix_execution_template_tasks_category_id", table_name="execution_template_tasks")
    op.drop_constraint("fk_execution_template_task_subcategory", "execution_template_tasks", type_="foreignkey")
    op.drop_constraint("fk_execution_template_task_category", "execution_template_tasks", type_="foreignkey")
    op.drop_column("execution_template_tasks", "subcategory_id")
    op.drop_column("execution_template_tasks", "category_id")

    op.drop_index("ix_vendors_migration_status", table_name="vendors")
    op.drop_index("ix_vendors_parent_vendor_id", table_name="vendors")
    op.drop_constraint("ck_vendor_ready_state", "vendors", type_="check")
    op.drop_constraint("ck_vendor_pending_state", "vendors", type_="check")
    op.drop_constraint("ck_vendor_migration_status", "vendors", type_="check")
    op.drop_constraint("ck_vendor_main_without_parent", "vendors", type_="check")
    op.drop_constraint("ck_vendor_sub_vendor_parent", "vendors", type_="check")
    op.drop_constraint("ck_vendor_engagement_type", "vendors", type_="check")
    op.drop_constraint("uq_contractor_relationship_subcontractor", "contractor_relationships", type_="unique")
    op.execute("""
        insert into contractor_relationships (id, main_contractor_id, subcontractor_id, created_by, created_at)
        select gen_random_uuid(), candidate_parent_vendor_id, vendor_id, resolved_by, now()
        from vendor_parent_migration_candidates candidate
        where candidate_parent_vendor_id is not null
          and not exists (
              select 1 from contractor_relationships relationship
              where relationship.main_contractor_id = candidate.candidate_parent_vendor_id
                and relationship.subcontractor_id = candidate.vendor_id
          )
    """)
    op.execute("""
        update vendors vendor
        set engagement_type = source.original_engagement_type
        from (
            select distinct on (vendor_id) vendor_id, original_engagement_type
            from vendor_parent_migration_candidates
            order by vendor_id, created_at
        ) source
        where vendor.id = source.vendor_id
    """)
    op.execute("update vendors set engagement_type = 'exclusive_subcontractor' where engagement_type = 'sub_vendor'")
    op.execute("update vendors set engagement_type = 'independent' where engagement_type = 'migration_pending'")
    op.drop_table("vendor_parent_migration_candidates")
    op.drop_constraint("fk_vendor_parent_vendor", "vendors", type_="foreignkey")
    op.drop_column("vendors", "migration_status")
    op.drop_column("vendors", "parent_vendor_id")

    op.drop_index("ix_vendor_categories_parent_id", table_name="vendor_categories")
    op.drop_constraint("ck_vendor_category_not_self_parent", "vendor_categories", type_="check")
    op.drop_constraint("ck_vendor_category_type", "vendor_categories", type_="check")
    op.drop_constraint("fk_vendor_category_parent", "vendor_categories", type_="foreignkey")
    op.drop_column("vendor_categories", "description")
    op.drop_column("vendor_categories", "parent_id")
    op.drop_column("vendor_categories", "category_type")