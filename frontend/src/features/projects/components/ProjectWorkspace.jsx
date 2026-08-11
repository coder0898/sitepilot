import { Activity, CalendarCheck, Gauge, Layers3, Pencil, ShieldCheck, Truck, UsersRound } from "lucide-react";
import { useEffect, useState } from "react";
import { projectsApi } from "../../../api/projectsApi";
import { Alert, LoadingSpinner, Pill } from "../../../components/ui";
import { ProjectActivityPane } from "./ProjectActivityPane";
import { ProjectDashboard } from "./ProjectDashboard";
import { ProjectDependencies } from "./ProjectDependencies";
import { ProjectExternalGates } from "./ProjectExternalGates";
import { ProjectLifecyclePane } from "./ProjectLifecyclePane";
import { ProjectOverviewPane } from "./ProjectOverviewPane";
import { ProjectSetupPane } from "./ProjectSetupPane";
import { ProjectTeamPane } from "./ProjectTeamPane";
import { ProjectTemplateReview } from "./ProjectTemplateReview";
import { ProjectVendorPanel } from "./ProjectVendorPanel";

const statusTone = { draft: "gray", active: "green", on_hold: "orange", completed: "blue", archived: "gray" };
const longDate = value => (value
  ? new Date(`${value}T00:00:00`).toLocaleDateString("en-GB", { day: "2-digit", month: "short", year: "numeric" })
  : "Not set");

// Supervisors and Internal Employees have no template-authoring role, and
// the matching backend routes reject them - hiding the panes keeps the tab
// strip honest rather than offering a guaranteed 403.
const PLANNING_PANES = ["template-review", "dependencies", "external-gates"];

function panesFor(project, role) {
  const first = project.status === "draft"
    ? ["overview", Layers3, "Setup"]
    : ["overview", CalendarCheck, "Overview"];
  const planning = [
    // Label only. The pane key stays "template-review" because it is in
    // shared URLs and matches the backend's own route names.
    ["template-review", Layers3, "Task Review"],
    ["dependencies", Layers3, "Dependencies"],
    ["external-gates", ShieldCheck, "External Gates"],
  ];
  return [
    first,
    ...(project.status === "draft" ? [] : [["dashboard", Gauge, "Dashboard"]]),
    ...(["supervisor", "internal_employee"].includes(role) ? [] : planning),
    ["team", UsersRound, "Team"],
    ["vendors", Truck, "Vendors"],
    ["lifecycle", ShieldCheck, "Lifecycle"],
    ["activity", Activity, "Activity"],
  ];
}

export function ProjectWorkspace({ projectId, references, templates = [], user, summary, attention, pane, onPaneChange, onEdit, onChanged, onDeleted }) {
  const [project, setProject] = useState(null);
  const [activity, setActivity] = useState([]);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);

  async function load() {
    setError("");
    try {
      const [detail, events] = await Promise.all([projectsApi.detail(projectId), projectsApi.activity(projectId)]);
      setProject(detail);
      setActivity(events);
    } catch (caught) {
      setError(caught?.message || "This project could not be loaded.");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    setLoading(true);
    setProject(null);
    load();
  }, [projectId]);

  async function changed() {
    await load();
    await onChanged();
  }

  if (loading) return <div className="p-6"><LoadingSpinner label="Opening project…"/></div>;
  if (error) return <Alert tone="danger" className="m-4">{error}</Alert>;
  if (!project) return null;

  const panes = panesFor(project, user.role);
  const activePane = panes.some(([key]) => key === pane) ? pane : "overview";
  const canEdit = ["admin", "super_admin"].includes(user.role)
    || project.memberships?.some(item => item.project_role === "project_manager" && item.user_id === user.id);

  function renderPane() {
    switch (activePane) {
      case "overview":
        return project.status === "draft"
          ? <ProjectSetupPane project={project} activity={activity} templates={templates} user={user} onChanged={changed} onOpenPane={onPaneChange}/>
          : <ProjectOverviewPane project={project} summary={summary} attention={attention} onOpenPane={onPaneChange}/>;
      case "dashboard": return <ProjectDashboard project={project}/>;
      case "template-review": return <ProjectTemplateReview projectId={project.id} user={user} projectStatus={project.status}/>;
      case "dependencies": return <ProjectDependencies project={project} user={user}/>;
      case "external-gates": return <ProjectExternalGates project={project} user={user}/>;
      case "team": return <ProjectTeamPane project={project} references={references} user={user} onChanged={changed}/>;
      case "vendors": return <ProjectVendorPanel project={project} user={user}/>;
      case "lifecycle": return <ProjectLifecyclePane project={project} user={user} onChanged={changed} onDeleted={onDeleted}/>;
      case "activity": return <ProjectActivityPane activity={activity}/>;
      default: return null;
    }
  }

  return <div className="flex min-h-0 min-w-0 flex-col">
    <header className="border-b border-slate-200 bg-white px-4 pb-0 pt-4 sm:px-5">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <h2 className="truncate text-lg font-black tracking-tight text-slate-950">{project.name}</h2>
          <p className="mt-0.5 truncate text-xs text-slate-500">
            {project.client_name} · <span className="font-mono text-[11px]">{project.code}</span>
          </p>
        </div>
        <div className="flex shrink-0 items-center gap-2">
          <Pill tone={statusTone[project.status]}>{project.status.replace("_", " ")}</Pill>
          {canEdit && <button
            type="button"
            onClick={() => onEdit(project)}
            className="inline-flex min-h-9 items-center gap-1.5 rounded-xl border border-slate-200 bg-white px-3 text-xs font-bold text-slate-600 transition hover:bg-slate-50 hover:text-slate-950"
          ><Pencil size={14} aria-hidden="true"/> Edit</button>}
        </div>
      </div>

      <dl className="mt-3 flex flex-wrap gap-x-6 gap-y-2">
        {[
          ["PM", project.memberships?.find(item => item.project_role === "project_manager")?.name || "Unassigned"],
          ["Supervisor", project.memberships?.find(item => item.project_role === "site_supervisor")?.name || "Unassigned"],
          ["Start", longDate(project.start_date)],
          ["Handover", longDate(project.target_handover_date)],
        ].map(([label, value]) => <div key={label} className="min-w-0">
          <dt className="font-mono text-[10px] uppercase tracking-[.1em] text-slate-400">{label}</dt>
          <dd className="truncate text-xs font-semibold text-slate-800">{value}</dd>
        </div>)}
      </dl>

      <nav aria-label="Project sections" className="-mx-4 mt-3 flex gap-1 overflow-x-auto px-4 sm:-mx-5 sm:px-5">
        {panes.map(([key, Icon, label]) => {
          const active = activePane === key;
          return <button
            key={key}
            type="button"
            onClick={() => onPaneChange(key)}
            aria-current={active ? "page" : undefined}
            className={`inline-flex min-h-10 shrink-0 items-center gap-1.5 whitespace-nowrap border-b-2 px-2.5 text-xs font-bold transition ${active ? "border-blue-600 text-blue-700" : "border-transparent text-slate-500 hover:text-slate-950"}`}
          ><Icon size={14} aria-hidden="true"/> {label}</button>;
        })}
      </nav>
    </header>

    <div className="min-h-0 flex-1 overflow-y-auto p-4 sm:p-5">{renderPane()}</div>
  </div>;
}
