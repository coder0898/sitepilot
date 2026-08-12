/**
 * U12: the arithmetic behind the 45-day timeline, kept out of the rendering.
 *
 * Day 1 is the project start date, inclusive - the same convention as
 * `plannedDate` in PhaseOverviewDrawer and `scheduled_date` on the server.
 * Every bar is expressed as a half-open CSS grid column range, so a task
 * running days 5 to 8 spans four columns rather than three.
 */

const MS_PER_DAY = 86_400_000;

/** The 1-based project day a timestamp falls on, or null. */
export function dayIndexOf(startDate, value) {
  if (!startDate || !value) return null;
  const start = new Date(`${startDate}T00:00:00Z`);
  const at = new Date(value);
  if (Number.isNaN(start.getTime()) || Number.isNaN(at.getTime())) return null;
  const startOfDay = Date.UTC(at.getUTCFullYear(), at.getUTCMonth(), at.getUTCDate());
  return Math.floor((startOfDay - start.getTime()) / MS_PER_DAY) + 1;
}

/**
 * One row per task that belongs on a timeline.
 *
 * A task with no planned days is excluded rather than drawn at column zero -
 * that is the pre-activation case, and putting it at the start of the
 * project would be a lie rather than a rounding error.
 */
export function buildTimelineRows(tasks, startDate, today = new Date()) {
  const todayIndex = dayIndexOf(startDate, today.toISOString());
  return tasks
    .filter(task => typeof task.planned_start_day === "number" && typeof task.planned_end_day === "number")
    .map(task => {
      const baselineStart = task.planned_start_day;
      const baselineEnd = Math.max(task.planned_end_day, baselineStart);
      const actualStart = dayIndexOf(startDate, task.actual_start_at);
      const actualFinish = dayIndexOf(startDate, task.actual_finish_at);
      // An unfinished task's bar runs to today, not to its baseline end -
      // the point of the view is to show work overrunning its plan.
      const actualEnd = actualStart == null
        ? null
        : Math.max(actualStart, actualFinish ?? todayIndex ?? actualStart);
      return {
        id: task.id,
        code: task.original_code,
        title: task.title,
        phase: task.phase,
        lifecycleStatus: task.lifecycle_status,
        baselineStart,
        baselineEnd,
        actualStart,
        actualEnd,
        isEarly: actualStart != null && actualStart < baselineStart,
        earlyStartReason: task.early_start_reason || null,
        isUnfinished: actualStart != null && actualFinish == null,
      };
    });
}

/** How many day columns the grid needs to hold every bar it will draw. */
export function timelineDayCount(rows, minimumDays = 45) {
  return rows.reduce(
    (widest, row) => Math.max(widest, row.baselineEnd, row.actualEnd ?? 0),
    Math.max(minimumDays, 1),
  );
}

/** Half-open CSS grid column range for a bar spanning `from`..`to` inclusive. */
export function columnSpan(from, to) {
  return `${Math.max(from, 1)} / ${Math.max(to, from) + 1}`;
}
