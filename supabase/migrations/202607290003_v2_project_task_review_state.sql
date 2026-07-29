alter table siteops_v2.project_tasks
    add column if not exists included boolean not null default true,
    add column if not exists decision_state text not null default 'pending_review';

alter table siteops_v2.project_tasks
    drop constraint if exists ck_v2_project_tasks_decision_state;

alter table siteops_v2.project_tasks
    add constraint ck_v2_project_tasks_decision_state
    check (decision_state in ('pending_review', 'included', 'excluded'));

alter table siteops_v2.project_tasks
    drop constraint if exists ck_v2_project_tasks_review_state_consistency;

alter table siteops_v2.project_tasks
    add constraint ck_v2_project_tasks_review_state_consistency
    check (
        (included = true and decision_state in ('pending_review', 'included'))
        or (included = false and decision_state = 'excluded')
    );

create index if not exists ix_v2_project_tasks_project_review
    on siteops_v2.project_tasks(project_id, included, decision_state, template_sequence);

revoke all on table siteops_v2.project_tasks from anon, authenticated;

comment on column siteops_v2.project_tasks.included is
    'Project-owned review inclusion. Generated tasks start included; exclusions require a deliberate later decision.';

comment on column siteops_v2.project_tasks.decision_state is
    'Project task review state: pending_review, included, or excluded.';
