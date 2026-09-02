-- Adds a "vacate" path to the PM/Supervisor role-change flow (BR-007):
-- ending an accountable role on an active project with no replacement named
-- yet ("empty the seat now, fill it later"), alongside the existing atomic
-- "replacement" path (name a successor and swap in one approved step).
--
-- 'temporary' (the other change_type this table's original CHECK allowed)
-- was never implemented anywhere in the application - dead since this
-- table's creation in 202608020005_v2_support_assignments_role_changes.sql -
-- so it is replaced here by the real second option rather than kept
-- alongside it.

alter table siteops_v2.project_role_changes
  alter column replacement_employee_id drop not null;

alter table siteops_v2.project_role_changes
  drop constraint project_role_changes_change_type_check;

alter table siteops_v2.project_role_changes
  add constraint project_role_changes_change_type_check
  check (change_type in ('replacement', 'vacate'));

-- A 'replacement' request always names who steps in; a 'vacate' request
-- never does - the role sits empty (surfaced via the project's normal
-- "Not assigned" display) until a later, separate replacement/add-team
-- action fills it.
alter table siteops_v2.project_role_changes
  add constraint ck_v2_project_role_changes_replacement_pair check (
    (change_type = 'replacement' and replacement_employee_id is not null)
    or (change_type = 'vacate' and replacement_employee_id is null)
  );
