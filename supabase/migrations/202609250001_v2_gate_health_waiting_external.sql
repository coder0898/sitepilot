-- Gate plan chunk 6: widens the external-approval health check to accept
-- 'waiting_external' ("Waiting on External") alongside
-- 'on_track'/'blocked'/'need_help'. Still an advisory progress update only -
-- never an approval lifecycle status (see
-- 202608210003_v2_project_external_approval_status_checks.sql).
--
-- The original constraint was declared inline, so Postgres named it
-- project_external_approval_status_checks_health_check. Both that name and
-- the SQLAlchemy model's name are dropped, and it is re-added under the
-- model's name so the two match from here on.

alter table siteops_v2.project_external_approval_status_checks
  drop constraint if exists project_external_approval_status_checks_health_check;
alter table siteops_v2.project_external_approval_status_checks
  drop constraint if exists ck_v2_project_external_approval_status_checks_health;
alter table siteops_v2.project_external_approval_status_checks
  add constraint ck_v2_project_external_approval_status_checks_health
  check (health in ('on_track', 'waiting_external', 'blocked', 'need_help'));
