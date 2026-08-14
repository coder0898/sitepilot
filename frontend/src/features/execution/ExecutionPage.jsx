import { useEffect, useMemo, useState } from "react";
import { CalendarCheck, CalendarRange, ClipboardList, FastForward, FolderKanban, GitBranch, Search, ShieldAlert, ShieldCheck } from "lucide-react";
import { projectsApi } from "../../api/projectsApi";
import { EmptyState, LoadingSpinner, Pill, Select } from "../../components/ui";
import { formatDateShort } from "../../utils/format";
import { ExecutionMetric as Metric } from "./components/ExecutionOverview";
import { ExternalApprovalsPanel } from "./components/ExternalApprovalsPanel";
import { ScheduleTimelinePanel } from "./components/ScheduleTimeline";
import { TaskExecutionBoard } from "./components/TaskExecutionBoard";
import { isReadyToAccelerate, READINESS_FILTERS, readinessCounts } from "./components/TaskReadinessPanel";

// U2 (Task Execution Engine, Phase 1): the "Tasks" tab is now the live
// TaskExecutionBoard - status transitions, evidence, verification/approval,
// blockers/delays and support assignment (U2-U6) all happen from here.
//
// U18: External Approvals is no longer a read-only planning view either. It
// now reads the execution-layer approvals and can decide them, so an approval
// that blocks tasks can actually be granted. Dependencies remains read-only.

export function ExecutionPage({ user }) {
  const [projects, setProjects] = useState([]);
  const [projectsLoading, setProjectsLoading] = useState(true);
  const [projectId, setProjectId] = useState("");
  const [view, setView] = useState(null);
  const [dependencies, setDependencies] = useState({ items: [], total: 0, excluded_warning_count: 0 });
  // U18: the project's memberships, which decide who may record an approval
  // decision - the same fact the backend checks, rather than the actor's
  // global role.
  const [project, setProject] = useState(null);
  const [activeTab, setActiveTab] = useState("tasks");
  const [detailLoading, setDetailLoading] = useState(false);
  const [search, setSearch] = useState("");
  const [error, setError] = useState("");
  // U19: the execution-layer tasks the board actually drew, handed up so the
  // tiles below count the same rows the user can see (R26).
  const [boardTasks, setBoardTasks] = useState([]);
  const [readinessFilter, setReadinessFilter] = useState("all");

  useEffect(() => {
    let active = true;
    setProjectsLoading(true);
    projectsApi.list({ status: "active" })
      .then(items => {
        if (!active) return;
        setProjects(items);
        setProjectId(current => (items.some(project => project.id === current) ? current : items[0]?.id || ""));
      })
      .catch(err => { if (active) setError(err.message || "Unable to load active projects."); })
      .finally(() => { if (active) setProjectsLoading(false); });
    return () => { active = false; };
  }, []);

  useEffect(() => {
    if (!projectId) {
      setView(null);
      setDependencies({ items: [], total: 0, excluded_warning_count: 0 });
      setProject(null);
      return;
    }
    let active = true;
    setDetailLoading(true);
    setError("");
    if (user.role === "internal_employee") {
      // executionTasks/dependencies/the project record are whole-project
      // baselines, not scoped to this actor - TaskExecutionBoard below
      // already fetches their own (server-filtered) task list directly, so
      // there's nothing project-wide for this role to load here. The
      // approvals tab this project record would authorise is not offered to
      // an Internal Employee either.
      setView(null);
      setDependencies({ items: [], total: 0, excluded_warning_count: 0 });
      setProject(null);
      setDetailLoading(false);
      return () => { active = false; };
    }
    Promise.all([projectsApi.executionTasks(projectId), projectsApi.dependencies(projectId), projectsApi.detail(projectId)])
      .then(([tasksResponse, dependenciesResponse, projectResponse]) => {
        if (!active) return;
        setView(tasksResponse);
        setDependencies(dependenciesResponse);
        setProject(projectResponse);
      })
      .catch(err => {
        if (!active) return;
        setView(null);
        setDependencies({ items: [], total: 0, excluded_warning_count: 0 });
        setProject(null);
        setError(err.message || "Unable to load this project's task baseline.");
      })
      .finally(() => { if (active) setDetailLoading(false); });
    return () => { active = false; };
  }, [projectId, user.role]);

  const selectedProject = projects.find(project => project.id === projectId);
  const counts = useMemo(() => readinessCounts(boardTasks), [boardTasks]);
  // Wrapped, not passed by reference: `filter` supplies (element, index,
  // array), and the index would land in this predicate's `today` parameter.
  const accelerable = useMemo(() => boardTasks.filter(task => isReadyToAccelerate(task)), [boardTasks]);

  // A project switch must not leave the previous project's tasks behind the
  // new project's tiles for the moment before the board reloads.
  useEffect(() => { setBoardTasks([]); setReadinessFilter("all"); }, [projectId]);

  return (
    <section className="grid gap-5">
      <header className="flex flex-col gap-4 rounded-[24px] border border-slate-200/80 bg-white p-5 shadow-[0_16px_50px_rgba(15,23,42,.06)] sm:p-6 lg:flex-row lg:items-end lg:justify-between">
        <div>
          <div className="flex items-center gap-2 text-[10px] font-black uppercase tracking-[.2em] text-blue-700"><CalendarCheck size={15}/> {user.role === "internal_employee" ? "Your assigned tasks" : "Active project task view"}</div>
          <h2 className="mt-2 text-2xl font-black tracking-[-.035em] text-slate-950 sm:text-3xl">{view?.project_name || selectedProject?.name || "Select an active project"}</h2>
          <p className="mt-2 max-w-2xl text-sm leading-6 text-slate-500">{user.role === "internal_employee" ? "Only tasks you're actively assigned to support appear here - update their status, log progress and upload evidence." : "Track and drive task execution for this activated project: status updates, evidence, verification/approval, blockers/delays and support assignment."}</p>
        </div>
        <label className="grid min-w-[240px] gap-2 text-sm font-bold text-slate-700">
          <span>Active project</span>
          <Select value={projectId} onChange={event => setProjectId(event.target.value)} disabled={projectsLoading}>
            <option value="">{projectsLoading ? "Loading..." : "Select project"}</option>
            {projects.map(project => <option key={project.id} value={project.id}>{project.name} ({project.code})</option>)}
          </Select>
        </label>
      </header>

      {error && <div className="rounded-2xl border border-rose-200 bg-rose-50 p-4 text-sm font-bold text-rose-700">{error}</div>}

      {!projectsLoading && !projects.length ? (
        <EmptyState icon={<FolderKanban size={21}/>} title="No activated projects yet" description="A task baseline appears here once Admin activates a project from its draft setup."/>
      ) : detailLoading ? (
        <div className="rounded-2xl border border-slate-200 bg-white p-8"><LoadingSpinner label="Loading task baseline..."/></div>
      ) : (view || (user.role === "internal_employee" && selectedProject)) ? (
        <>
          {/* U19 (R26): these count the EXECUTION rows the board below drew,
              handed up by the board itself. They used to come from the
              planning read model, which counts tasks excluded from the plan
              and never instantiated into the execution layer - so the number
              above the board did not describe the board, and no amount of
              looking at it would tell you why. Only shown to a role that gets
              the whole-project view; an Internal Employee's list is filtered
              to their own assignments and a project-wide count would be a
              claim about work they cannot see. */}
          {view && <div className="grid grid-cols-2 gap-3 lg:grid-cols-3" role="group" aria-label="Readiness summary">
            <Metric icon={<ClipboardList/>} label="Total tasks" value={counts.total} helper="In this project's execution layer" tone="blue"/>
            <Metric icon={<ShieldCheck/>} label="Ready" value={counts.ready} helper="Dependencies and approvals met" tone="green"/>
            <Metric icon={<ShieldAlert/>} label="Blocked" value={counts.blocked} helper={counts.blocked ? "Waiting on a task or approval" : "Nothing is held up"} tone={counts.blocked ? "red" : "green"}/>
          </div>}
          {/* No "could start early" tile: the section below already carries
              that count in its own heading, and two numbers for one fact is
              how a surface starts disagreeing with itself. */}

          {/* An Internal Employee only ever sees their own assigned tasks
              here (server-filtered - see list_project_tasks) - Dependencies
              and External Approvals are whole-project planning views with
              nothing "assigned" about them, so they're not offered. */}
          {user.role !== "internal_employee" && <div className="rounded-2xl border border-slate-200 bg-white p-2">
            <div className="flex flex-wrap gap-2">
              {[
                ["tasks", "Tasks", ClipboardList],
                ["timeline", "Timeline", CalendarRange],
                ["dependencies", "Dependencies", GitBranch],
                ["approvals", "External Approvals", ShieldCheck],
              ].map(([key, label, Icon]) => (
                <button key={key} onClick={() => setActiveTab(key)} className={`flex items-center gap-2 rounded-xl px-4 py-2 text-sm font-bold transition ${activeTab === key ? "bg-blue-600 text-white" : "bg-slate-100 text-slate-600"}`}>
                  <Icon size={16}/>{label}
                </button>
              ))}
            </div>
          </div>}

          {activeTab === "tasks" && <>
          {/* U19 (R20): work that could be pulled forward - ready to start,
              but not due to start yet. Shown above the board rather than as
              another filter because it answers a question the board does not:
              not "what is ready" but "what could we get ahead on". */}
          {view && <section className="rounded-2xl border border-violet-200 bg-violet-50/60 p-4">
            <h3 className="flex items-center gap-2 text-xs font-black uppercase tracking-wide text-violet-800">
              <FastForward size={14}/> Could start early
              {accelerable.length > 0 && <Pill tone="violet">{accelerable.length}</Pill>}
            </h3>
            {accelerable.length ? <div className="mt-3 grid gap-2">
              {accelerable.map(task => <div key={task.id} className="flex flex-wrap items-center gap-2 rounded-xl border border-violet-200 bg-white px-3 py-2 text-sm">
                <span className="font-mono text-xs font-black text-blue-700">{task.original_code}</span>
                <span className="min-w-0 flex-1 truncate font-bold text-slate-900">{task.title}</span>
                <span className="text-xs font-bold text-slate-500">Planned {formatDateShort(task.planned_start_date)}</span>
              </div>)}
            </div> : <p className="mt-2 text-sm text-slate-500">
              Nothing can be pulled forward right now - every ready task is already due to start, or is waiting on something.
            </p>}
          </section>}

          <div className="grid gap-3 rounded-2xl border border-slate-200 bg-white p-3 sm:grid-cols-[minmax(0,1fr)_auto] sm:items-center">
            <label className="relative block">
              <Search className="pointer-events-none absolute left-3.5 top-1/2 -translate-y-1/2 text-slate-400" size={18}/>
              <input value={search} onChange={event => setSearch(event.target.value)} className="min-h-12 w-full rounded-xl border border-slate-200 bg-white pl-11 pr-4 text-sm outline-none transition placeholder:text-slate-400 focus:border-blue-600 focus:ring-4 focus:ring-blue-600/10" placeholder="Search task code, title, phase or category"/>
            </label>
            {/* Narrows the same list the search narrows - the two compose. */}
            <div className="flex flex-wrap gap-2" role="group" aria-label="Filter by readiness">
              {READINESS_FILTERS.map(([key, label]) => (
                <button
                  key={key}
                  type="button"
                  aria-pressed={readinessFilter === key}
                  onClick={() => setReadinessFilter(key)}
                  className={`min-h-11 rounded-xl px-4 text-sm font-bold transition ${readinessFilter === key ? "bg-blue-600 text-white" : "bg-slate-100 text-slate-600"}`}
                >{label}</button>
              ))}
            </div>
          </div>

          {/* U18: the tabs are mutually exclusive, so leaving Tasks unmounts
              this board and returning remounts it - which is what refetches
              the readiness an approval decision just changed. Nothing extra
              is needed to recompute the view, and adding a refresh signal
              alongside would be a second mechanism doing the same work. If
              these tabs ever render together, that stops being true. */}
          <TaskExecutionBoard
            projectId={projectId}
            user={user}
            search={search}
            readinessFilter={readinessFilter}
            onTasksLoaded={setBoardTasks}
          />
          </>}

          {activeTab === "timeline" && <ScheduleTimelinePanel projectId={projectId}/>}

          {activeTab === "dependencies" && <div className="rounded-2xl border border-slate-200 bg-white p-5">
            <h3 className="m-0 font-serif text-lg text-slate-950">Task dependencies</h3>
            {dependencies.items?.length ? (
              <div className="mt-4 grid gap-2">
                {dependencies.items.map(dep => (
                  <div key={dep.id} className="flex flex-wrap items-center gap-2 rounded-xl border border-slate-200 bg-slate-50 px-4 py-3 text-sm">
                    <span className="font-bold text-slate-900">{dep.predecessor_title}</span>
                    <Pill tone={dep.blocking ? "orange" : "gray"}>{dep.dependency_type.replaceAll("_", " ")}</Pill>
                    <span className="font-bold text-slate-900">{dep.successor_title}</span>
                    {dep.excluded_task_warning && <Pill tone="red">References an excluded task</Pill>}
                  </div>
                ))}
              </div>
            ) : (
              <p className="mt-3 text-sm text-slate-500">No dependencies were generated for this project.</p>
            )}
          </div>}

          {activeTab === "approvals" && <ExternalApprovalsPanel projectId={projectId} project={project} user={user}/>}        </>
      ) : !error && (
        <EmptyState icon={<CalendarCheck size={21}/>} title="Select an active project" description="Choose an activated project above to view its task baseline."/>
      )}
    </section>
  );
}
