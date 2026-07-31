import { useEffect, useMemo, useState } from "react";
import { CalendarCheck, ClipboardList, FolderKanban, GitBranch, Layers, ListChecks, Search, ShieldCheck } from "lucide-react";
import { projectsApi } from "../../api/projectsApi";
import { EmptyState, LoadingSpinner, Pill, Select, Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "../../components/ui";
import { ExecutionMetric as Metric } from "./components/ExecutionOverview";

// Phase 9: the Execution tab is a read-only Active Project Task View.
// It shows the task baseline an activated V2 project already has -
// nothing here writes to the backend. Task execution (status changes,
// evidence, verification, approval), the calendar, supervisor actions and
// support-employee assignment are explicitly out of scope for this phase
// and are not implemented anywhere in this file.

const DECISION_TONE = { included: "green", pending_review: "orange", excluded: "gray" };
const decisionLabel = value => String(value || "").replaceAll("_", " ");

function plannedDayLabel(task) {
  if (!task.planned_start_day) return "Pre-activation";
  if (task.planned_end_day && task.planned_end_day !== task.planned_start_day) return `Day ${task.planned_start_day}-${task.planned_end_day}`;
  return `Day ${task.planned_start_day}`;
}

export function ExecutionPage() {
  const [projects, setProjects] = useState([]);
  const [projectsLoading, setProjectsLoading] = useState(true);
  const [projectId, setProjectId] = useState("");
  const [view, setView] = useState(null);
  const [dependencies, setDependencies] = useState({ items: [], total: 0, excluded_warning_count: 0 });
  const [externalGates, setExternalGates] = useState([]);
  const [activeTab, setActiveTab] = useState("tasks");
  const [detailLoading, setDetailLoading] = useState(false);
  const [search, setSearch] = useState("");
  const [error, setError] = useState("");

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
      setExternalGates([]);
      return;
    }
    let active = true;
    setDetailLoading(true);
    setError("");
    Promise.all([projectsApi.executionTasks(projectId), projectsApi.dependencies(projectId), projectsApi.externalGates(projectId)])
      .then(([tasksResponse, dependenciesResponse, gatesResponse]) => {
        if (!active) return;
        setView(tasksResponse);
        setDependencies(dependenciesResponse);
        setExternalGates(gatesResponse?.items || gatesResponse || []);
      })
      .catch(err => {
        if (!active) return;
        setView(null);
        setDependencies({ items: [], total: 0, excluded_warning_count: 0 });
        setExternalGates([]);
        setError(err.message || "Unable to load this project's task baseline.");
      })
      .finally(() => { if (active) setDetailLoading(false); });
    return () => { active = false; };
  }, [projectId]);

  const filteredTasks = useMemo(() => {
    const tasks = view?.tasks || [];
    const term = search.trim().toLowerCase();
    if (!term) return tasks;
    return tasks.filter(task => [task.code, task.title, task.category, task.phase].some(value => value && value.toLowerCase().includes(term)));
  }, [view, search]);

  return (
    <section className="grid gap-5">
      <header className="flex flex-col gap-4 rounded-[24px] border border-slate-200/80 bg-white p-5 shadow-[0_16px_50px_rgba(15,23,42,.06)] sm:p-6 lg:flex-row lg:items-end lg:justify-between">
        <div>
          <div className="flex items-center gap-2 text-[10px] font-black uppercase tracking-[.2em] text-blue-700"><CalendarCheck size={15}/> Active project task view</div>
          <h2 className="mt-2 text-2xl font-black tracking-[-.035em] text-slate-950 sm:text-3xl">{view?.project_name || "Select an active project"}</h2>
          <p className="mt-2 max-w-2xl text-sm leading-6 text-slate-500">Read-only view of the generated task baseline for an activated project. Status updates, assignments, evidence and approvals are not part of this view.</p>
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
      ) : view ? (
        <>
          <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
            <Metric icon={<ClipboardList/>} label="Total tasks" value={view.total_tasks} helper={`${view.included_task_count} included in plan`} tone="blue"/>
            <Metric icon={<ListChecks/>} label="Included tasks" value={view.included_task_count} helper="Part of the active plan" tone="green"/>
            <Metric icon={<Layers/>} label="Excluded tasks" value={view.excluded_task_count} helper="Marked not applicable" tone="orange"/>
            <Metric icon={<GitBranch/>} label="Dependencies" value={dependencies.total || 0} helper={dependencies.excluded_warning_count ? `${dependencies.excluded_warning_count} reference excluded tasks` : "Blocking sequence"} tone="violet"/>
          </div>

          <div className="rounded-2xl border border-slate-200 bg-white p-2">
            <div className="flex flex-wrap gap-2">
              {[
                ["tasks", "Tasks", ClipboardList],
                ["dependencies", "Dependencies", GitBranch],
                ["approvals", "External Approvals", ShieldCheck],
              ].map(([key, label, Icon]) => (
                <button key={key} onClick={() => setActiveTab(key)} className={`flex items-center gap-2 rounded-xl px-4 py-2 text-sm font-bold transition ${activeTab === key ? "bg-blue-600 text-white" : "bg-slate-100 text-slate-600"}`}>
                  <Icon size={16}/>{label}
                </button>
              ))}
            </div>
          </div>

          {activeTab === "tasks" && <>
          <div className="rounded-2xl border border-slate-200 bg-white p-3">
            <label className="relative block">
              <Search className="pointer-events-none absolute left-3.5 top-1/2 -translate-y-1/2 text-slate-400" size={18}/>
              <input value={search} onChange={event => setSearch(event.target.value)} className="min-h-12 w-full rounded-xl border border-slate-200 bg-white pl-11 pr-4 text-sm outline-none transition placeholder:text-slate-400 focus:border-blue-600 focus:ring-4 focus:ring-blue-600/10" placeholder="Search task code, title, phase or category"/>
            </label>
          </div>

          <div className="overflow-hidden rounded-2xl border border-slate-200 bg-white">
            {filteredTasks.length ? (
              <Table>
                <TableHead>
                  <TableRow>
                    <TableHeader>Task</TableHeader>
                    <TableHeader>Phase / Category</TableHeader>
                    <TableHeader>Kind</TableHeader>
                    <TableHeader>Planned day</TableHeader>
                    <TableHeader>Baseline status</TableHeader>
                    <TableHeader>Plan decision</TableHeader>
                  </TableRow>
                </TableHead>
                <TableBody>
                  {filteredTasks.map(task => (
                    <TableRow key={task.id}>
                      <TableCell><strong className="block text-slate-950">{task.title}</strong><span className="text-xs text-slate-400">{task.code}</span></TableCell>
                      <TableCell>{[task.phase, task.category].filter(Boolean).join(" / ") || "-"}</TableCell>
                      <TableCell className="capitalize">{task.task_kind}{task.task_class === "class_a" ? " · Class A" : ""}</TableCell>
                      <TableCell>{plannedDayLabel(task)}</TableCell>
                      <TableCell><Pill tone="gray">{task.lifecycle_status}</Pill></TableCell>
                      <TableCell><Pill tone={DECISION_TONE[task.decision_state] || "gray"}>{decisionLabel(task.decision_state)}</Pill></TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            ) : (
              <EmptyState icon={<ClipboardList size={21}/>} title={view.tasks.length ? "No tasks match this search" : "No task baseline generated"} description={view.tasks.length ? "Try a different search term." : "This project was activated before its task baseline was generated."}/>
            )}
          </div>
          </>}

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

          {activeTab === "approvals" && <div className="rounded-2xl border border-slate-200 bg-white p-5">
            <h3 className="m-0 font-serif text-lg text-slate-950">External approvals</h3>
            <p className="mt-1 text-sm text-slate-500">Read-only view of project external gate records.</p>
            {externalGates.length ? (
              <div className="mt-4 grid gap-3">
                {externalGates.map(gate => (
                  <article key={gate.id} className="rounded-2xl border border-slate-200 bg-white p-4">
                    <div className="flex flex-wrap items-start justify-between gap-3">
                      <div className="min-w-0">
                        <div className="flex flex-wrap items-center gap-2">
                          {gate.code && <span className="text-xs font-black text-blue-700">{gate.code}</span>}
                          <Pill tone="orange">{String(gate.status || "pending_review").replaceAll("_", " ")}</Pill>
                          <Pill tone={gate.applicability_state === "applicable" ? "green" : "orange"}>
                            {String(gate.applicability_state || "pending_review").replaceAll("_", " ")}
                          </Pill>
                          {gate.mapping_classification && <Pill tone="gray">{String(gate.mapping_classification).replaceAll("_", " ")}</Pill>}
                        </div>
                        <h4 className="mt-2 font-black text-slate-950">{gate.approval_name || gate.name || "External approval"}</h4>
                        {gate.description && <p className="mt-1 text-sm text-slate-600">{gate.description}</p>}
                      </div>
                      {gate.sequence && <span className="text-xs font-bold text-slate-400">#{gate.sequence}</span>}
                    </div>
                    <div className="mt-4 grid gap-2 text-xs sm:grid-cols-3">
                      <div className="rounded-xl bg-slate-50 p-3"><span className="block font-black uppercase tracking-wide text-slate-400">Source</span><strong className="mt-1 block text-slate-700">{gate.source === "project_manual" ? "Manual" : "Template"}</strong></div>
                      <div className="rounded-xl bg-slate-50 p-3"><span className="block font-black uppercase tracking-wide text-slate-400">PM owner</span><strong className="mt-1 block text-slate-700">{gate.accountable_pm_name || "Not assigned"}</strong></div>
                      <div className="rounded-xl bg-slate-50 p-3"><span className="block font-black uppercase tracking-wide text-slate-400">Mapping</span><strong className="mt-1 block text-slate-700">{gate.exact_task_count ? `${gate.exact_task_count} task links` : gate.broad_mapping_text || "Configuration required"}</strong>{gate.blocking && <small className="mt-1 block font-bold text-rose-600">Blocking</small>}</div>
                    </div>
                  </article>
                ))}
              </div>
            ) : <p className="mt-3 text-sm text-slate-500">No external approvals available for this project.</p>}
          </div>}        </>
      ) : !error && (
        <EmptyState icon={<CalendarCheck size={21}/>} title="Select an active project" description="Choose an activated project above to view its task baseline."/>
      )}
    </section>
  );
}
