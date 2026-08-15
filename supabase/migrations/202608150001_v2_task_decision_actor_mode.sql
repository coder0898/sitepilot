-- Records whether a verification/approval decision was made by the role
-- that normally owns it, or by an Admin/Super Admin standing in for it -
-- and, when standing in, whether an active Supervisor/PM actually existed
-- on the project at decision time (a genuine BR-007 fallback) or not (an
-- Admin overriding someone who was available). Previously indistinguishable
-- in the data: `_require_verifier`/`_require_approver` always let
-- Admin/Super Admin through with no record of which case applied.

alter table siteops_v2.task_verifications
  add column if not exists decision_mode text not null default 'role_normal'
    check (decision_mode in ('role_normal', 'pm_fallback', 'admin_fallback', 'admin_override'));

alter table siteops_v2.task_approval_decisions
  add column if not exists decision_mode text not null default 'role_normal'
    check (decision_mode in ('role_normal', 'admin_fallback', 'admin_override'));
