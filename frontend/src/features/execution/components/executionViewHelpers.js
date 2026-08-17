import { todayIso } from "../../../utils/format";

// Shared, pure helpers used by every role-specific execution view
// (ExecutionCalendarView, SupervisorOperationsBoard, MyAssignedWorkList,
// TaskActionView). Nothing here calls an API or holds state - it only
// reshapes the same task array `taskExecutionApi.list` already returns.

const DAY_MS = 86400000;

// Dates arrive as either a plain date ("2026-09-01") or an instant
// ("2026-09-01T09:15:00Z"). Both are reduced to the CALENDAR DAY in UTC - the
// same basis the backend wrote planned dates on. Parsing an instant in local
// time would slide a bar a day either way for anyone east or west of UTC.
// (Moved verbatim from the retired ScheduleTimeline.jsx.)
export function toDay(value) {
  if (!value) return null;
  const parsed = new Date(`${String(value).slice(0, 10)}T00:00:00Z`);
  return Number.isNaN(parsed.getTime()) ? null : parsed;
}

export function daysBetween(from, to) {
  return Math.round((to - from) / DAY_MS);
}

export function isDated(task) {
  return Boolean(task.planned_start_date || task.actual_start_at);
}

export function plannedRange(task) {
  const start = toDay(task.planned_start_date);
  const end = toDay(task.planned_end_date) || start;
  return start ? { start, end } : null;
}

// The actual range's end: the recorded finish, or today for work still in
// flight. A cancelled task never finished and never accrues to today.
export function actualRange(task, today) {
  const start = toDay(task.actual_start_at);
  if (!start) return null;
  const finish = toDay(task.actual_finish_at);
  if (finish) return { start, end: finish };
  if (task.lifecycle_status === "cancelled") return { start, end: start };
  return { start, end: today, running: true };
}

// The span every bar/column is positioned against. Built from the planned
// dates AND the actuals AND today, so a task that ran past its baseline
// cannot draw off the end of the grid.
export function timelineSpan(tasks, today) {
  const bounds = [];
  for (const task of tasks) {
    const planned = plannedRange(task);
    const actual = actualRange(task, today);
    if (planned) bounds.push(planned.start, planned.end);
    if (actual) bounds.push(actual.start, actual.end);
  }
  if (!bounds.length) return null;
  const start = new Date(Math.min(...bounds.map(Number)));
  const end = new Date(Math.max(...bounds.map(Number), Number(today)));
  // Inclusive of the last day, so a single-day span is one day wide rather
  // than zero and every bar divides by something.
  return { start, end, days: daysBetween(start, end) + 1 };
}

// 1-based CSS grid line numbers for a date range within a span, e.g. for use
// as `style={{ gridColumn: gridColumnFor(span, range) }}`.
export function gridColumnFor(span, range) {
  const offset = daysBetween(span.start, range.start);
  const length = daysBetween(range.start, range.end) + 1;
  return `${offset + 1} / ${offset + 1 + Math.max(length, 1)}`;
}

// Whether `day` (a UTC-midnight Date) falls inside a task's occupied span -
// its planned range if dated, else its actual range. Used to bucket a task
// into the Supervisor board's Yesterday/Today/Tomorrow columns.
export function taskOccupiesDay(task, day, today) {
  const planned = plannedRange(task);
  if (planned) return day >= planned.start && day <= planned.end;
  const actual = actualRange(task, today);
  if (actual) return day >= actual.start && day <= actual.end;
  return false;
}

// U19's readinessCounts, extended with the lifecycle/variance buckets the
// mockup's metric tiles need (In Progress / Completed / Delayed). `ready` and
// `blocked` stay sourced from `task.readiness.state` exactly as before -
// nothing here re-derives readiness, only tallies it alongside two more facts
// the payload already carries (`lifecycle_status`, `variance.status`).
export function executionCounts(tasks) {
  const counts = { total: tasks.length, ready: 0, in_progress: 0, completed: 0, delayed: 0, blocked: 0 };
  for (const task of tasks) {
    if (task.readiness?.state === "ready") counts.ready += 1;
    if (task.readiness?.state === "blocked") counts.blocked += 1;
    if (task.lifecycle_status === "in_progress") counts.in_progress += 1;
    if (task.lifecycle_status === "completed") counts.completed += 1;
    if (task.variance?.status === "late") counts.delayed += 1;
  }
  return counts;
}

// The status buckets the metric tiles and their matching filters use. "all"
// is not itself a bucket - it is the absence of a filter.
export const STATUS_BUCKETS = [
  ["all", "All"],
  ["ready", "Ready to Start"],
  ["in_progress", "In Progress"],
  ["completed", "Completed"],
  ["delayed", "Delayed"],
  ["blocked", "Blocked"],
];

export function matchesStatusBucket(task, bucket) {
  if (!bucket || bucket === "all") return true;
  if (bucket === "ready") return task.readiness?.state === "ready";
  if (bucket === "blocked") return task.readiness?.state === "blocked";
  if (bucket === "in_progress") return task.lifecycle_status === "in_progress";
  if (bucket === "completed") return task.lifecycle_status === "completed";
  if (bucket === "delayed") return task.variance?.status === "late";
  return true;
}

// "Day N" / "Day N-M" / "Pre-activation" - moved verbatim from
// TaskExecutionBoard.jsx, reused by the calendar's row label and My
// Assigned Work's Planned Dates column.
export function plannedDayLabel(task) {
  if (!task.planned_start_day) return "Pre-activation";
  if (task.planned_end_day && task.planned_end_day !== task.planned_start_day) return `Day ${task.planned_start_day}-${task.planned_end_day}`;
  return `Day ${task.planned_start_day}`;
}

export function todayAsDay() {
  return toDay(todayIso());
}
