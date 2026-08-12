-- 45-day scheduling POC integration, U10: stop asking a human how many
-- days a delay cost.
--
-- Delay is a measurement, not an opinion. It is the gap between a task's
-- target finish and when it actually finished (or now, if it has not), and
-- nobody in execution should be able to influence it - which a free-text
-- day count plainly does. New delay events therefore record *why* and *who
-- is responsible* and stop recording *how many days*.
--
-- The column and its existing rows stay. Historical delay events remain
-- readable exactly as recorded; they are simply never added to computed
-- delay, and never reinterpreted as one.
--
-- SAME NAMING TRAP AS 202608120001. 202608020004 declared this check
-- inline and unnamed:
--
--     impact_days integer not null check (impact_days > 0),
--
-- so Postgres auto-named it `task_delay_events_impact_days_check` while
-- the ORM declares the same rule as
-- `ck_v2_task_delay_events_impact_days_positive`. Dropping only the ORM
-- name would be a no-op against a real database and would leave the
-- original still refusing a null. Both names are dropped, `if exists`, for
-- the same reason as before: a database built from ORM metadata has only
-- one of them and an unqualified drop would abort the transaction.

BEGIN;

ALTER TABLE siteops_v2.task_delay_events
  DROP CONSTRAINT IF EXISTS task_delay_events_impact_days_check,
  DROP CONSTRAINT IF EXISTS ck_v2_task_delay_events_impact_days_positive,
  ADD CONSTRAINT ck_v2_task_delay_events_impact_days_positive
    CHECK (impact_days IS NULL OR impact_days > 0);

ALTER TABLE siteops_v2.task_delay_events
  ALTER COLUMN impact_days DROP NOT NULL;

COMMIT;
