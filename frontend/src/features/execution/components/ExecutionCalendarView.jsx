import {
  CalendarRange, CheckCircle2, ChevronDown, ChevronLeft, ChevronRight, ClipboardList,
  Clock3, ListChecks, PlayCircle, RotateCcw, Search, ShieldAlert, ShieldCheck, Target,
} from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import { projectsApi } from "../../../api/projectsApi";
import { taskExecutionApi } from "../../../api/taskExecutionApi";
import { Button, EmptyState, LoadingSpinner, Pill, Select } from "../../../components/ui";
import { formatDateShort } from "../../../utils/format";
import { STATUS_TONE } from "./TaskDetailContent";
import { TaskDetailDrawer } from "./TaskDetailDrawer";
import { blockingReasonKinds, COMPUTED_READINESS_STATES, readinessLabel, readinessTone, REASON_ICON } from "./TaskReadinessPanel";
import {
  actualRange, daysBetween, executionCounts, gridColumnFor, matchesStatusBucket,
  plannedRange, STATUS_BUCKETS, timelineSpan, todayAsDay,
} from "./executionViewHelpers";

// A real Gantt grid, not floating pills: a fixed-width LEFT task table (code,
// title, phase/category, status - always readable, never inside a bar) and a
// horizontally-scrolling RIGHT date grid whose header and task-bar rows share
// one `gridTemplateColumns`, so a bar's grid-column always lines up with the
// date it's drawn under. Column width is a fixed px (not `1fr`/minmax) on
// purpose - a flexible track would let the grid shrink to fit the viewport
// instead of overflowing it, which is exactly what made horizontal scrolling
// unreliable before.
const ZOOM_PRESETS = { week: 100, month: 72, full: 44 };
const ZOOM_LABELS = { week: "Week", month: "Month", full: "Full" };
const DEFAULT_ZOOM = "month";
const ROW_HEIGHT = 64;
const GROUP_HEADER_HEIGHT = 40;
const DATE_HEADER_HEIGHT = 56;
const LEFT_PANE_WIDTH = 360;
// The calendar body scrolls internally instead of stretching the page - a
// viewport-relative cap (not a fixed px figure) so it still fits comfortably
// under whatever header/KPI/filter chrome sits above it at any screen size.
const CALENDAR_BODY_HEIGHT_CLASS = "max-h-[68vh] min-h-[420px]";

const TILE_ICONS = { total: ClipboardList, ready: ShieldCheck, in_progress: PlayCircle, completed: CheckCircle2, delayed: Clock3, blocked: ShieldAlert };
const TILE_TONES = {
  total: "text-blue-700 bg-blue-50",
  ready: "text-emerald-700 bg-emerald-50",
  in_progress: "text-blue-700 bg-blue-50",
  completed: "text-emerald-700 bg-emerald-50",
  delayed: "text-amber-700 bg-amber-50",
  blocked: "text-rose-700 bg-rose-50",
};

// Tailwind class strings must be literal for the JIT compiler to pick them
// up, so status tones map to a fixed background palette here rather than
// interpolating the Pill tone name into a class.
const TONE_BG = {
  blue: "bg-blue-600",
  green: "bg-emerald-600",
  orange: "bg-amber-500",
  red: "bg-rose-600",
  gray: "bg-slate-400",
};

function weekdayHeader(date) {
  return date.toLocaleDateString("en-GB", { weekday: "short", timeZone: "UTC" });
}
function dayHeader(date) {
  return date.toLocaleDateString("en-GB", { day: "2-digit", month: "short", timeZone: "UTC" });
}
function daysInSpan(span) {
  return Array.from({ length: span.days }, (_, index) => {
    const date = new Date(span.start);
    date.setUTCDate(date.getUTCDate() + index);
    return date;
  });
}
function isWeekend(date) {
  const day = date.getUTCDay();
  return day === 0 || day === 6;
}

// A single-row, low-height stat chip - the "huge vertical KPI cards" the
// design review flagged replaced with something that reads at a glance
// without eating page height.
function CompactStat({ icon: Icon, label, value, tone }) {
  return <div className={`flex items-center gap-2 rounded-xl border border-slate-200 bg-white px-3 py-2 ${TILE_TONES[tone] || ""}`}>
    <Icon size={15}/>
    <span className="text-sm font-black leading-none text-slate-950">{value}</span>
    <span className="text-[10px] font-bold uppercase leading-none tracking-wide text-slate-500">{label}</span>
  </div>;
}

const REASON_LABEL = { dependency: "Blocked by a dependent task", approval: "Blocked by an external approval" };

// Small icon-per-reason-kind badge - a dependency icon, an approval icon, or
// both together when a task is blocked by both at once - instead of one
// generic "blocked" mark that doesn't say why. `kinds` comes straight off
// the same `readiness.reasons` the drawer's own Readiness panel already
// reads; nothing here re-derives or duplicates that engine's verdict.
function BlockingReasonBadges({ task, tone = "pill" }) {
  const kinds = blockingReasonKinds(task);
  if (!kinds.length) return null;
  return <span className="inline-flex items-center gap-1">
    {kinds.map(kind => {
      const Icon = REASON_ICON[kind];
      return <span
        key={kind}
        title={REASON_LABEL[kind]}
        className={`grid size-4 place-items-center rounded-full ${tone === "pill" ? "bg-rose-100 text-rose-700" : "bg-rose-600 text-white shadow"}`}
      ><Icon size={10}/></span>;
    })}
  </span>;
}

// One task's row in the RIGHT date grid: schedule only, no title text. A
// grey baseline bar is the plan; a colored bar (when the task has actually
// started) is reality, drawn as a second lane so both stay visible at once.
// Nothing here is fabricated - the "remaining" tail is only ever drawn from
// real fields (today, planned_end_date) and only while genuinely in
// progress, never as an invented forecast/percentage.
function TaskBarRow({ task, span, today, gridTemplateColumns, dayColumnPx, onOpen }) {
  const planned = plannedRange(task);
  const actual = actualRange(task, today);
  const late = task.variance?.status === "late";
  const blocked = task.readiness?.state === "blocked";
  // Empty when the task is blocked by its lifecycle state rather than a
  // named dependency/approval reason - TaskReadinessPanel falls back the
  // same way, so this mirrors it rather than inventing a third case.
  const blockingKinds = blockingReasonKinds(task);
  const statusColor = late ? TONE_BG.red : (TONE_BG[STATUS_TONE[task.lifecycle_status]] || TONE_BG.gray);
  const plannedOffsetDays = daysBetween(span.start, planned.start);
  const laterEnd = actual && actual.end > planned.end ? actual.end : planned.end;
  const laterEndOffsetDays = daysBetween(span.start, laterEnd) + 1;
  // In-progress work whose planned finish is still ahead of today gets a
  // lighter tail from today to that planned finish - the remaining span on
  // the SAME baseline the grey bar already shows, not a separate estimate.
  const remaining = task.lifecycle_status === "in_progress" && today < planned.end
    ? { start: today, end: planned.end }
    : null;

  return <button
    type="button"
    onClick={onOpen}
    title={`${task.original_code} - ${task.title}`}
    style={{ height: ROW_HEIGHT }}
    className="group relative block w-full border-b border-slate-100 text-left transition hover:bg-blue-50/40"
  >
    <div className="pointer-events-none absolute inset-0 grid items-start" style={{ gridTemplateColumns }}>
      <div style={{ gridColumn: gridColumnFor(span, planned) }} className={`mt-3 h-3 rounded-full ${actual ? "bg-slate-300" : `${statusColor} opacity-70`}`}/>
    </div>
    {remaining && <div className="pointer-events-none absolute inset-0 grid items-start" style={{ gridTemplateColumns }}>
      <div style={{ gridColumn: gridColumnFor(span, remaining) }} className="mt-3 h-3 rounded-full bg-[repeating-linear-gradient(45deg,#e2e8f0,#e2e8f0_4px,transparent_4px,transparent_8px)]"/>
    </div>}
    {actual && <div className="pointer-events-none absolute inset-0 grid items-end" style={{ gridTemplateColumns }}>
      <div style={{ gridColumn: gridColumnFor(span, actual) }} className={`mb-3 h-2.5 rounded-full ${statusColor}`}/>
    </div>}
    {blocked && <span
      className="pointer-events-none absolute top-1/2 z-10 flex -translate-y-1/2 gap-0.5"
      style={{ left: `${Math.max(plannedOffsetDays * dayColumnPx - 8, 4)}px` }}
    >
      {blockingKinds.length ? blockingKinds.map(kind => {
        const Icon = REASON_ICON[kind];
        return <span key={kind} title={REASON_LABEL[kind]} className="grid size-4 place-items-center rounded-full bg-rose-600 text-white shadow"><Icon size={10}/></span>;
      }) : <span title="Blocked" className="grid size-4 place-items-center rounded-full bg-rose-600 text-white shadow"><ShieldAlert size={10}/></span>}
    </span>}
    {late && <span
      className="pointer-events-none absolute top-1/2 z-10 -translate-y-1/2 whitespace-nowrap rounded-full bg-rose-100 px-1.5 py-0.5 text-[10px] font-black text-rose-700"
      style={{ left: `${laterEndOffsetDays * dayColumnPx + 4}px` }}
    >{task.variance.days}d delay</span>}
  </button>;
}

// One task's row in the LEFT fixed table: code, title, phase/category and a
// status chip - everything a bar could never show without truncating.
function TaskListRow({ task, onOpen }) {
  return <button
    type="button"
    onClick={onOpen}
    title={`${task.original_code} - ${task.title}`}
    style={{ height: ROW_HEIGHT }}
    className="flex w-full items-center gap-2 border-b border-slate-100 px-4 text-left transition hover:bg-blue-50/40"
  >
    <div className="min-w-0 flex-1">
      <div className="flex items-center gap-1.5">
        <span className="font-mono text-[10px] font-black text-blue-700">{task.original_code}</span>
        {COMPUTED_READINESS_STATES.includes(task.readiness?.state) && <Pill tone={readinessTone(task.readiness.state)}>{readinessLabel(task.readiness.state)}</Pill>}
        <BlockingReasonBadges task={task}/>
      </div>
      <div className="truncate text-sm font-bold text-slate-900">{task.title}</div>
      <div className="truncate text-[11px] text-slate-400">{[task.phase, task.category].filter(Boolean).join(" / ") || "Unphased"}</div>
    </div>
    <Pill tone={STATUS_TONE[task.lifecycle_status] || "gray"}>{task.lifecycle_status.replaceAll("_", " ")}</Pill>
  </button>;
}

// Tasks with no planned_start_date/planned_end_date can't sit on the date
// grid at all - not "not yet dated" as an afterthought dumped below it, but
// a compact, business-named card above it: work still waiting to be
// scheduled, not a data-quality problem. Collapsed to just its header and
// status chips by default; the list itself is opt-in.
function PreActivationChecklist({ tasks, onOpen }) {
  const [expanded, setExpanded] = useState(false);
  const readyCount = tasks.filter(task => task.readiness?.state === "ready").length;
  const blockedCount = tasks.filter(task => task.readiness?.state === "blocked").length;
  const inProgressCount = tasks.filter(task => task.lifecycle_status === "in_progress").length;

  return <section className="rounded-2xl border border-slate-200 bg-white shadow-sm">
    <button type="button" onClick={() => setExpanded(value => !value)} aria-expanded={expanded} className="flex w-full flex-wrap items-center justify-between gap-2 p-4 text-left">
      <div className="flex items-center gap-2">
        <ListChecks className="text-blue-700" size={18}/>
        <div>
          <h3 className="font-serif text-base text-slate-950">Pre-Activation Checklist</h3>
          <p className="text-xs font-bold text-slate-500">{tasks.length} task{tasks.length === 1 ? "" : "s"} waiting to be scheduled</p>
        </div>
      </div>
      <div className="flex items-center gap-2">
        <div className="flex flex-wrap gap-1.5">
          <Pill tone="green">{readyCount} Ready</Pill>
          <Pill tone="red">{blockedCount} Blocked</Pill>
          <Pill tone="blue">{inProgressCount} In Progress</Pill>
        </div>
        <ChevronDown size={16} className={`shrink-0 text-slate-400 transition ${expanded ? "rotate-180" : ""}`}/>
      </div>
    </button>

    {expanded && <div className="grid gap-1.5 border-t border-slate-100 p-4 pt-3">
      {tasks.map(task => <button key={task.id} type="button" onClick={() => onOpen(task.id)} className="flex flex-wrap items-center gap-2 rounded-xl border border-slate-100 bg-slate-50 px-3 py-2 text-left text-sm transition hover:bg-slate-100">
        <span className="font-mono text-xs font-black text-blue-700">{task.original_code}</span>
        <span className="min-w-0 flex-1 truncate font-bold text-slate-900">{task.title}</span>
        {COMPUTED_READINESS_STATES.includes(task.readiness?.state) && <Pill tone={readinessTone(task.readiness.state)}>{readinessLabel(task.readiness.state)}</Pill>}
        <BlockingReasonBadges task={task}/>
        <Pill tone={STATUS_TONE[task.lifecycle_status] || "gray"}>{task.lifecycle_status.replaceAll("_", " ")}</Pill>
      </button>)}
    </div>}
  </section>;
}

// Admin / PM / Super Admin: the whole-project Gantt-style calendar that
// replaces the old Tasks + Timeline tabs. Fetches its own tasks and project
// membership, same pattern the old TaskExecutionBoard used.
export function ExecutionCalendarView({ projectId, user }) {
  const [tasks, setTasks] = useState([]);
  const [project, setProject] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [search, setSearch] = useState("");
  const [phaseFilter, setPhaseFilter] = useState("all");
  const [statusFilter, setStatusFilter] = useState("all");
  const [dateFrom, setDateFrom] = useState("");
  const [dateTo, setDateTo] = useState("");
  const [selectedTaskId, setSelectedTaskId] = useState(null);
  const [collapsedPhases, setCollapsedPhases] = useState(() => new Set());
  const [zoom, setZoom] = useState(DEFAULT_ZOOM);
  const rightPaneRef = useRef(null);

  async function load() {
    setLoading(true);
    setError("");
    try {
      const items = await taskExecutionApi.list(projectId);
      setTasks(items);
    } catch (caught) {
      setError(caught?.message || "The execution calendar could not be loaded.");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => { load(); }, [projectId]);
  useEffect(() => {
    let active = true;
    setProject(null);
    projectsApi.detail(projectId).then(detail => { if (active) setProject(detail); }).catch(() => { if (active) setProject(null); });
    return () => { active = false; };
  }, [projectId]);

  const counts = useMemo(() => executionCounts(tasks), [tasks]);
  const phases = useMemo(() => Array.from(new Set(tasks.map(task => task.phase).filter(Boolean))), [tasks]);
  const candidates = (project?.memberships || []).filter(m => m.project_role === "internal_employee");

  const term = search.trim().toLowerCase();
  const filtered = tasks.filter(task => {
    if (!matchesStatusBucket(task, statusFilter)) return false;
    if (phaseFilter !== "all" && task.phase !== phaseFilter) return false;
    // A date-range filter only means something for a task that HAS planned
    // dates - it narrows the calendar's date-wise view, not the
    // Pre-Activation Checklist, which is undated by definition.
    if (dateFrom && task.planned_end_date && task.planned_end_date < dateFrom) return false;
    if (dateTo && task.planned_start_date && task.planned_start_date > dateTo) return false;
    if (!term) return true;
    return [task.original_code, task.title, task.category, task.phase].some(value => value && value.toLowerCase().includes(term));
  });

  // The grid draws PLANNED bars, so a task belongs on it only when it has a
  // planned range - not merely "dated", which would also admit a task dated
  // solely by its actuals (no planned_start_date) and carry a null planned
  // range into `gridColumnFor`.
  const dated = filtered.filter(task => plannedRange(task));
  const undated = filtered.filter(task => !plannedRange(task));
  const today = todayAsDay();
  const span = timelineSpan(dated, today);

  const selectedTask = tasks.find(task => task.id === selectedTaskId) || null;
  const filtersActive = Boolean(search.trim()) || phaseFilter !== "all" || statusFilter !== "all" || Boolean(dateFrom) || Boolean(dateTo);
  const dayColumnPx = ZOOM_PRESETS[zoom];

  function togglePhase(phase) {
    setCollapsedPhases(prev => {
      const next = new Set(prev);
      if (next.has(phase)) next.delete(phase); else next.add(phase);
      return next;
    });
  }

  function resetFilters() {
    setSearch("");
    setPhaseFilter("all");
    setStatusFilter("all");
    setDateFrom("");
    setDateTo("");
  }

  function scrollByWeek(direction) {
    rightPaneRef.current?.scrollBy({ left: direction * 7 * dayColumnPx, behavior: "smooth" });
  }

  function scrollToToday() {
    if (!rightPaneRef.current || todayOffset == null) return;
    rightPaneRef.current.scrollTo({ left: Math.max(todayOffset * dayColumnPx - 2 * dayColumnPx, 0), behavior: "smooth" });
  }

  if (loading) return <div className="rounded-2xl border border-slate-200 bg-white p-8"><LoadingSpinner label="Loading execution calendar..."/></div>;
  if (error) return <div className="rounded-2xl border border-rose-200 bg-rose-50 p-5 text-sm font-bold text-rose-700">{error}</div>;
  if (!tasks.length) return <EmptyState icon={<CalendarRange size={21}/>} title="No execution tasks yet" description="This project's baseline has no tasks to execute."/>;

  // Grouped by phase, in the order phases first appear in the task list
  // (template sequence) - the real taxonomy this project's baseline was
  // authored with, not a hardcoded phase list that might not match it.
  const phaseOrder = [];
  const byPhase = new Map();
  for (const task of dated) {
    const phase = task.phase || "Unphased";
    if (!byPhase.has(phase)) { byPhase.set(phase, []); phaseOrder.push(phase); }
    byPhase.get(phase).push(task);
  }

  const gridTemplateColumns = span ? `repeat(${span.days}, ${dayColumnPx}px)` : undefined;
  const gridWidthPx = span ? span.days * dayColumnPx : 0;
  const todayOffset = span ? daysBetween(span.start, today) : null;
  const todayInSpan = span && todayOffset >= 0 && todayOffset < span.days;
  const days = span ? daysInSpan(span) : [];

  {/* TaskDetailDrawer is a fixed-position overlay now, not a split column -
      no grid-cols split needed to host it. */}
  return <div className="grid gap-4">
    <div className="grid min-w-0 gap-4">
      <div className="flex flex-wrap items-end justify-between gap-2">
        <div>
          <h2 className="font-serif text-xl text-slate-950">Execution Calendar</h2>
          <p className="mt-0.5 text-xs font-bold text-slate-500">
            {span ? `${formatDateShort(span.start.toISOString().slice(0, 10))} → ${formatDateShort(span.end.toISOString().slice(0, 10))} · ${span.days} days` : "No dated tasks yet"}
          </p>
        </div>
      </div>

      <div className="flex flex-wrap gap-2" role="group" aria-label="Execution summary">
        <CompactStat icon={TILE_ICONS.total} label="Total" value={counts.total} tone="total"/>
        <CompactStat icon={TILE_ICONS.ready} label="Ready" value={counts.ready} tone="ready"/>
        <CompactStat icon={TILE_ICONS.in_progress} label="In progress" value={counts.in_progress} tone="in_progress"/>
        <CompactStat icon={TILE_ICONS.completed} label="Completed" value={counts.completed} tone="completed"/>
        <CompactStat icon={TILE_ICONS.delayed} label="Delayed" value={counts.delayed} tone="delayed"/>
        <CompactStat icon={TILE_ICONS.blocked} label="Blocked" value={counts.blocked} tone="blocked"/>
      </div>

      <div className="flex flex-wrap items-center gap-2 rounded-2xl border border-slate-200 bg-white p-3 shadow-sm">
        <label className="relative min-w-[200px] flex-1">
          <Search className="pointer-events-none absolute left-3.5 top-1/2 -translate-y-1/2 text-slate-400" size={18}/>
          <input value={search} onChange={event => setSearch(event.target.value)} className="min-h-10 w-full rounded-xl border border-slate-200 bg-white pl-10 pr-3 text-sm outline-none transition placeholder:text-slate-400 focus:border-blue-600 focus:ring-4 focus:ring-blue-600/10" placeholder="Search task code, title, phase or category"/>
        </label>
        <Select value={phaseFilter} onChange={event => setPhaseFilter(event.target.value)} aria-label="Filter by phase" className="min-h-10 w-auto min-w-[140px]">
          <option value="all">All phases</option>
          {phases.map(phase => <option key={phase} value={phase}>{phase}</option>)}
        </Select>
        <Select value={statusFilter} onChange={event => setStatusFilter(event.target.value)} aria-label="Filter by status" className="min-h-10 w-auto min-w-[150px]">
          {STATUS_BUCKETS.map(([key, label]) => <option key={key} value={key}>{label}</option>)}
        </Select>
        {/* Assignee filter is intentionally not offered: the task list
            payload carries only support-assignment COUNTS, never assignee
            names, so there is nothing real to filter by yet. */}
        <input type="date" value={dateFrom} onChange={event => setDateFrom(event.target.value)} aria-label="From date" className="min-h-10 rounded-xl border border-slate-200 bg-white px-2.5 text-sm text-slate-700 outline-none focus:border-blue-600 focus:ring-4 focus:ring-blue-600/10"/>
        <span className="text-xs font-bold text-slate-400">to</span>
        <input type="date" value={dateTo} onChange={event => setDateTo(event.target.value)} aria-label="To date" className="min-h-10 rounded-xl border border-slate-200 bg-white px-2.5 text-sm text-slate-700 outline-none focus:border-blue-600 focus:ring-4 focus:ring-blue-600/10"/>
        <button
          type="button"
          onClick={resetFilters}
          disabled={!filtersActive}
          className="flex min-h-10 items-center gap-1.5 rounded-xl px-3 text-sm font-bold text-slate-500 transition hover:bg-slate-100 disabled:cursor-not-allowed disabled:opacity-40"
        ><RotateCcw size={14}/> Reset</button>
      </div>

      {undated.length > 0 && <PreActivationChecklist tasks={undated} onOpen={setSelectedTaskId}/>}

      {!dated.length && !undated.length && (
        <EmptyState icon={<CalendarRange size={21}/>} title="No tasks match" description="No task matches these filters."/>
      )}

      {span && dated.length > 0 && (
        <div className="calendarShell overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-sm">
          {/* Compact timeline controls - real navigation over the same
              already-rendered grid (scroll position, column width), never a
              second copy of the data. */}
          <div className="flex flex-wrap items-center justify-between gap-2 border-b border-slate-100 px-3 py-2">
            <div className="flex items-center gap-1">
              <button type="button" onClick={() => scrollByWeek(-1)} aria-label="Scroll back a week" className="rounded-lg p-1.5 text-slate-500 transition hover:bg-slate-100"><ChevronLeft size={16}/></button>
              <button type="button" onClick={() => scrollByWeek(1)} aria-label="Scroll forward a week" className="rounded-lg p-1.5 text-slate-500 transition hover:bg-slate-100"><ChevronRight size={16}/></button>
              <button type="button" onClick={scrollToToday} disabled={!todayInSpan} className="flex items-center gap-1.5 rounded-lg px-2.5 py-1.5 text-xs font-bold text-slate-600 transition hover:bg-slate-100 disabled:cursor-not-allowed disabled:opacity-40"><Target size={13}/> Today</button>
            </div>
            <div className="flex items-center gap-1 rounded-lg bg-slate-100 p-1" role="group" aria-label="Zoom">
              {Object.keys(ZOOM_PRESETS).map(key => (
                <button
                  key={key}
                  type="button"
                  aria-pressed={zoom === key}
                  onClick={() => setZoom(key)}
                  className={`rounded-md px-2.5 py-1 text-xs font-bold transition ${zoom === key ? "bg-white text-blue-700 shadow-sm" : "text-slate-500"}`}
                >{ZOOM_LABELS[key]}</button>
              ))}
            </div>
          </div>

          {/* One shared vertical scroll region for BOTH panes, so the left
              task table and the right date grid scroll down together in
              lockstep (they're just normal-flow siblings inside it - no JS
              scroll-sync needed) while the page itself stays a fixed
              height instead of growing with every task.
              `items-start` matters here, not just `flex`: without it, the
              default `align-items: stretch` forces rightPane to exactly this
              container's capped height - and per the CSS overflow spec, a
              box with `overflow-x: auto` and `overflow-y: visible` has its
              visible axis silently promoted to `auto` too, so a
              height-constrained rightPane quietly became its OWN vertical
              scroll container, fighting this one for a second scrollbar.
              `items-start` lets both panes size to their natural (equal,
              same-row-heights) content height instead, so only THIS
              container ever has something to scroll. */}
          <div className={`ganttBody flex items-start overflow-y-auto ${CALENDAR_BODY_HEIGHT_CLASS}`}>
            {/* LEFT FIXED TASK TABLE */}
            <div className="leftPane sticky left-0 z-10 flex-none border-r border-slate-200 bg-white" style={{ width: LEFT_PANE_WIDTH }}>
              <div style={{ height: DATE_HEADER_HEIGHT }} className="sticky top-0 z-20 flex items-center border-b border-slate-200 bg-slate-50 px-4">
                <span className="text-[11px] font-black uppercase tracking-wide text-slate-500">Task</span>
              </div>
              {phaseOrder.map(phase => {
                const collapsed = collapsedPhases.has(phase);
                const items = byPhase.get(phase);
                return <div key={phase}>
                  <button type="button" onClick={() => togglePhase(phase)} style={{ height: GROUP_HEADER_HEIGHT }} className="flex w-full items-center gap-1.5 border-b border-slate-100 bg-slate-50 px-4 text-left text-[11px] font-black uppercase tracking-wide text-slate-600">
                    <ChevronDown size={13} className={`shrink-0 transition ${collapsed ? "-rotate-90" : ""}`}/>
                    <span className="truncate">{phase}</span>{" "}
                    <span className="text-slate-400">({items.length})</span>
                  </button>
                  {!collapsed && items.map(task => <TaskListRow key={task.id} task={task} onOpen={() => setSelectedTaskId(task.id)}/>)}
                </div>;
              })}
            </div>

            {/* RIGHT HORIZONTAL DATE GRID - one horizontal scroll container
                for the header and every bar row, so they can never drift
                apart; the date header stays pinned to the top of the
                SHARED vertical scroll above via its own sticky offset. */}
            <div ref={rightPaneRef} className="rightPane min-w-0 flex-1 overflow-x-auto overflow-y-visible">
              <div className="relative" style={{ width: gridWidthPx }}>
                <div className="sticky top-0 z-10 grid border-b border-slate-200 bg-slate-50" style={{ height: DATE_HEADER_HEIGHT, gridTemplateColumns }}>
                  {days.map((date, index) => <div key={index} className={`flex flex-col items-center justify-center border-r border-slate-100 ${isWeekend(date) ? "bg-slate-100/70" : ""}`}>
                    <span className="text-[10px] font-bold uppercase text-slate-400">{weekdayHeader(date)}</span>
                    <span className="text-[11px] font-black text-slate-700">{dayHeader(date)}</span>
                  </div>)}
                </div>

                {/* Weekend column tint, spanning the full body beneath the
                    header - a background layer, painted before the bars so
                    it never sits on top of them. */}
                <div className="pointer-events-none absolute inset-x-0 bottom-0 grid" style={{ top: DATE_HEADER_HEIGHT, gridTemplateColumns }}>
                  {days.map((date, index) => <div key={index} className={`border-r border-slate-100 ${isWeekend(date) ? "bg-slate-50" : ""}`}/>)}
                </div>

                {todayInSpan && <div
                  aria-label="Today"
                  className="pointer-events-none absolute inset-y-0 z-20 w-0.5 bg-blue-600"
                  style={{ left: `${todayOffset * dayColumnPx}px` }}
                />}

                {phaseOrder.map(phase => {
                  const collapsed = collapsedPhases.has(phase);
                  const items = byPhase.get(phase);
                  return <div key={phase} className="relative">
                    <div style={{ height: GROUP_HEADER_HEIGHT }} className="border-b border-slate-100 bg-slate-50/80"/>
                    {!collapsed && items.map(task => (
                      <TaskBarRow key={task.id} task={task} span={span} today={today} gridTemplateColumns={gridTemplateColumns} dayColumnPx={dayColumnPx} onOpen={() => setSelectedTaskId(task.id)}/>
                    ))}
                  </div>;
                })}
              </div>
            </div>
          </div>
        </div>
      )}
    </div>

    {selectedTask && <TaskDetailDrawer
      key={selectedTask.id}
      projectId={projectId}
      project={project}
      task={selectedTask}
      user={user}
      candidates={candidates}
      onClose={() => setSelectedTaskId(null)}
      onChanged={load}
    />}
  </div>;
}
