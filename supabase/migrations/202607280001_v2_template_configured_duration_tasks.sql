-- Phase 2 task authoring: keep row-local schedule integrity in PostgreSQL.
-- The upper bound is version-specific and is enforced transactionally by FastAPI;
-- PostgreSQL cannot express that cross-row check as a CHECK constraint.
begin;

alter table siteops_v2.v2_template_tasks
    drop constraint if exists ck_v2_template_tasks_schedule_days;

alter table siteops_v2.v2_template_tasks
    add constraint ck_v2_template_tasks_schedule_days check (
        (
            schedule_classification = 'pre_activation'
            and planned_start_day is null
            and planned_end_day is null
        )
        or
        (
            schedule_classification = 'execution'
            and planned_start_day >= 1
            and planned_end_day >= 1
        )
    );

comment on constraint ck_v2_template_tasks_schedule_days
    on siteops_v2.v2_template_tasks is
    'Row-local schedule shape. FastAPI enforces execution-day upper bounds against template version duration_days.';

commit;