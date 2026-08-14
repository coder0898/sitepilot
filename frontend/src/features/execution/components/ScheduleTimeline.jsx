import { CalendarRange } from "lucide-react";
import { useEffect, useState } from "react";
import { taskExecutionApi } from "../../../api/taskExecutionApi";
import { EmptyState, LoadingSpinner, Pill } from "../../../components/ui";
import { formatDateShort, todayIso } from "../../../utils/format";

// U16: the baseline against the actuals, side by side.
//
// Everything here is drawn from the payload U15 already ships - planned
// dates from U9, actuals from U10, variance from U13. Nothing is recomputed:
// in particular the early/late verdict is the backend's, because a second
// arithmetic here could disagree with the dashboards about whether a task ran
// late, and two numbers for one fact is how a surface starts contradicting
// itself.
//
// No charting dependency. The bars are positioned divs over a percentage
// scale, which is all a date span needs and nothing to keep updated.

const DAY_MS = 86400000;

// Dates arrive as either a plain date ("2026-09-01") or an instant
// ("2026-09-01T09:15:00Z"). Both are reduced to the CALENDAR DAY in UTC -
// the same basis U9 wrote the planned dates on and U13 measures variance on.
// Parsing an instant in local time would slide a bar a day either way for
// anyone east or west of UTC.
function toDay(value) {
  if (!value) return null;
  const parsed = new Date(`${String(value).slice(0, 10)}T00:00:00Z`);
  return Number.isNaN(parsed.getTime()) ? null : parsed;
}

function daysBetween(from, to) {
  return Math.round((to - from) / DAY_MS);
}

// The actual bar's end: the recorded finish, or today for work still in
// flight. A cancelled task never finished and never accrues to today - the
// same rule U13 applies, mirrored rather than re-decided.
function actualRange(task, today) {
  const start = toDay(task.actual_start_at);
  if (!start) return null;
  const finish = toDay(task.actual_finish_at);
  if (finish) return { start, end: finish };
  if (task.lifecycle_status === "cancelled") return { start, end: start };
  return { start, end: today, running: true };
}

function plannedRange(task) {
  const start = toDay(task.planned_start_date);
  const end = toDay(task.planned_end_date) || start;
  return start ? { start, end } : null;
}

export function isDated(task) {
  return Boolean(task.planned_start_date || task.actual_start_at);
}

// The span every bar is positioned against. Built from the planned dates AND
// the actuals AND today, so a task that ran past its baseline - exactly the
// case this view exists to show - cannot draw off the end of the track.
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
  // Inclusive of the last day, so a single-day project is one day wide
  // rather than zero and every bar divides by something.
  return { start, end, days: daysBetween(start, end) + 1 };
}

function barStyle(span, { start, end }) {
  const offset = daysBetween(span.start, start);
  const length = daysBetween(start, end) + 1;
  return {
    left: `${(offset / span.days) * 100}%`,
    width: `${Math.max(length / span.days, 0.5 / span.days) * 100}%`,
  };
}

const VARIANCE_TONE = { early: "green", on_time: "blue", late: "red" };
const VARIANCE_LABEL = {
  early: days => `${days}d early`,
  on_time: () => "On time",
  late: days => `${days}d late`,
};

function VariancePill({ variance }) {
  if (!variance || !VARIANCE_LABEL[variance.status]) return null;
  return <Pill tone={VARIANCE_TONE[variance.status] || "gray"}>{VARIANCE_LABEL[variance.status](variance.days)}</Pill>;
}

function TaskRow({ task, span, today }) {
  const planned = plannedRange(task);
  const actual = actualRange(task, today);
  return <div className="grid grid-cols-[minmax(0,11rem)_minmax(0,1fr)] items-center gap-3 py-1.5">
    <div className="min-w-0">
      <span className="font-mono text-[11px] font-black text-blue-700">{task.original_code}</span>
      <span className="block truncate text-xs font-bold text-slate-700">{task.title}</span>
    </div>
    <div className="relative h-8 rounded-lg bg-slate-100">
      {planned && <div
        aria-label={`Baseline for ${task.original_code}`}
        title={`Planned ${formatDateShort(task.planned_start_date)} - ${formatDateShort(task.planned_end_date || task.planned_start_date)}`}
        className="absolute top-1 h-3 rounded-full bg-slate-400"
        style={barStyle(span, planned)}
      />}
      {actual && <div
        aria-label={`Actual for ${task.original_code}`}
        title={actual.running ? `Started ${formatDateShort(task.actual_start_at)}, still running` : `Actual ${formatDateShort(task.actual_start_at)} - ${formatDateShort(task.actual_finish_at)}`}
        className={`absolute bottom-1 h-3 rounded-full ${actual.running ? "bg-blue-400" : "bg-blue-600"}`}
        style={barStyle(span, actual)}
      />}
    </div>
  </div>;
}

function TaskCard({ task, today }) {
  const actual = actualRange(task, today);
  return <article className="rounded-xl border border-slate-200 bg-white p-3">
    <div className="flex flex-wrap items-center gap-2">
      <span className="font-mono text-[11px] font-black text-blue-700">{task.original_code}</span>
      <span className="min-w-0 flex-1 truncate text-sm font-bold text-slate-900">{task.title}</span>
      <VariancePill variance={task.variance}/>
    </div>
    <dl className="mt-2 grid grid-cols-2 gap-2 text-xs">
      <div><dt className="font-black uppercase tracking-wide text-slate-400">Planned</dt><dd className="mt-0.5 font-bold text-slate-700">{task.planned_start_date ? `${formatDateShort(task.planned_start_date)} - ${formatDateShort(task.planned_end_date || task.planned_start_date)}` : "Not dated"}</dd></div>
      <div><dt className="font-black uppercase tracking-wide text-slate-400">Actual</dt><dd className="mt-0.5 font-bold text-slate-700">{actual ? (actual.running ? `${formatDateShort(task.actual_start_at)} - running` : `${formatDateShort(task.actual_start_at)} - ${formatDateShort(task.actual_finish_at)}`) : "Not started"}</dd></div>
    </dl>
  </article>;
}

// Fetches its own tasks, like ExternalApprovalsPanel does. The alternative -
// reading the array the board handed up - would only work because the Tasks
// tab happens to be the default and therefore always loads first, and would
// empty this view silently the day that changed.
export function ScheduleTimelinePanel({ projectId }) {
  const [tasks, setTasks] = useState(null);
  const [error, setError] = useState("");

  useEffect(() => {
    let active = true;
    setTasks(null);
    setError("");
    taskExecutionApi.list(projectId)
      .then(items => { if (active) setTasks(items); })
      .catch(caught => { if (active) { setError(caught?.message || "This project's schedule could not be loaded."); setTasks([]); } });
    return () => { active = false; };
  }, [projectId]);

  if (error) return <div className="rounded-2xl border border-rose-200 bg-rose-50 p-4 text-sm font-bold text-rose-700">{error}</div>;
  if (tasks === null) return <div className="rounded-2xl border border-slate-200 bg-white p-8"><LoadingSpinner label="Loading schedule..."/></div>;
  return <ScheduleTimeline tasks={tasks}/>;
}

export function ScheduleTimeline({ tasks = [] }) {
  const today = toDay(todayIso());
  const dated = tasks.filter(isDated);
  const span = timelineSpan(dated, today);

  if (!span) {
    return <EmptyState
      icon={<CalendarRange size={21}/>}
      title="No dated tasks yet"
      description="A timeline appears once this project is activated and its tasks carry planned dates."
    />;
  }

  // Grouped by phase, in the order the phases first appear - which is
  // template sequence, the order the list already arrives in. Sorting
  // alphabetically would scramble a construction sequence into nonsense.
  const phases = [];
  const byPhase = new Map();
  for (const task of dated) {
    const phase = task.phase || "Unphased";
    if (!byPhase.has(phase)) { byPhase.set(phase, []); phases.push(phase); }
    byPhase.get(phase).push(task);
  }

  const todayOffset = `${(daysBetween(span.start, today) / span.days) * 100}%`;
  const todayInSpan = today >= span.start && today <= span.end;

  return <section className="rounded-2xl border border-slate-200 bg-white p-4 sm:p-5" aria-label="Baseline versus actual timeline">
    <div className="flex flex-wrap items-center justify-between gap-3">
      <h3 className="m-0 font-serif text-lg text-slate-950">Baseline vs actual</h3>
      <div className="flex flex-wrap items-center gap-3 text-xs font-bold text-slate-500">
        <span className="flex items-center gap-1.5"><i className="h-2.5 w-6 rounded-full bg-slate-400"/> Planned</span>
        <span className="flex items-center gap-1.5"><i className="h-2.5 w-6 rounded-full bg-blue-600"/> Actual</span>
        <span>{formatDateShort(span.start.toISOString().slice(0, 10))} - {formatDateShort(span.end.toISOString().slice(0, 10))}</span>
      </div>
    </div>

    {/* Desktop: the timeline proper. Mobile gets cards instead - a 45-day
        horizontal span on a phone is either unreadably dense or a sideways
        scroll nobody discovers, and the same facts read fine as a list. */}
    <div className="mt-4 hidden md:block" data-region="timeline">
      <div className="relative">
        {todayInSpan && <div
          aria-label="Today"
          className="pointer-events-none absolute bottom-0 top-0 z-10 w-px bg-rose-500"
          style={{ left: `calc(11rem + 0.75rem + (100% - 11rem - 0.75rem) * ${daysBetween(span.start, today) / span.days})` }}
        />}
        {phases.map(phase => <div key={phase} className="mb-3 last:mb-0">
          <h4 className="text-[11px] font-black uppercase tracking-wide text-slate-500">{phase}</h4>
          <div className="mt-1">{byPhase.get(phase).map(task => <TaskRow key={task.id} task={task} span={span} today={today}/>)}</div>
        </div>)}
      </div>
      <p className="mt-2 text-xs text-slate-400">Today is marked at {todayInSpan ? formatDateShort(todayIso()) : "outside this span"} ({todayOffset} across).</p>
    </div>

    <div className="mt-4 grid gap-3 md:hidden" data-region="cards">
      {phases.map(phase => <div key={phase}>
        <h4 className="text-[11px] font-black uppercase tracking-wide text-slate-500">{phase}</h4>
        <div className="mt-1 grid gap-2">{byPhase.get(phase).map(task => <TaskCard key={task.id} task={task} today={today}/>)}</div>
      </div>)}
    </div>
  </section>;
}
