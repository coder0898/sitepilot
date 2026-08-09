import { Activity, FolderKanban } from "lucide-react";
import { useEffect, useState } from "react";
import { adminVisibilityApi } from "../../api/adminVisibilityApi";
import { EmptyState, LoadingSpinner, Pill } from "../../components/ui";

const statusTone = { draft: "gray", active: "green", on_hold: "orange", completed: "blue", archived: "gray" };

const TILE_TONE_CLASSES = {
  slate: "border-slate-200 bg-slate-50",
  rose: "border-rose-300 bg-rose-50",
  amber: "border-amber-300 bg-amber-50",
  emerald: "border-emerald-300 bg-emerald-50",
};

function ProjectOverviewRow({ project }) {
  return <article className="grid gap-3 rounded-2xl border border-slate-200 bg-white p-4">
    <div className="flex flex-wrap items-center justify-between gap-2">
      <div><span className="text-[10px] font-black uppercase tracking-[.16em] text-blue-700">{project.code}</span><h3 className="mt-0.5 font-black text-slate-950">{project.name}</h3></div>
      <Pill tone={statusTone[project.status] || "gray"}>{project.status.replace("_", " ")}</Pill>
    </div>
    <div className="grid grid-cols-3 gap-2 sm:grid-cols-7">
      {[
        ["Planned", project.planned_count, "slate"],
        ["Active", project.active_count, "slate"],
        ["Completed", project.completed_count, "emerald"],
        ["Blocked", project.blocked_count, "rose"],
        ["Delayed", project.delayed_count, "amber"],
        ["Overdue", project.overdue_count, "rose"],
        ["No update", project.no_update_count, "amber"],
      ].map(([label, value, tone]) => <div key={label} className={`rounded-xl border p-2 text-center ${TILE_TONE_CLASSES[value > 0 ? tone : "slate"]}`}>
        <p className="text-[9px] font-black uppercase tracking-wider text-slate-500">{label}</p>
        <p className="text-lg font-black text-slate-950">{value}</p>
      </div>)}
    </div>
  </article>;
}

export function AdminProjectsOverview() {
  const [projects, setProjects] = useState([]);
  const [activity, setActivity] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  async function load() {
    setLoading(true);
    setError("");
    try {
      const [overview, events] = await Promise.all([
        adminVisibilityApi.projectsOverview(),
        adminVisibilityApi.activity({ limit: 50 }),
      ]);
      setProjects(overview);
      setActivity(events);
    } catch (caught) {
      setError(caught?.message || "The portfolio overview could not be loaded.");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => { load(); }, []);

  if (loading) return <div className="grid min-h-40 place-items-center"><LoadingSpinner label="Loading portfolio overview..."/></div>;

  return <div className="grid gap-6">
    {error && <div className="rounded-xl border border-rose-200 bg-rose-50 p-3 text-sm font-bold text-rose-700">{error}</div>}

    <section>
      <h2 className="mb-3 flex items-center gap-2 text-lg font-black text-slate-950"><FolderKanban size={18}/> Portfolio rollup</h2>
      {projects.length === 0
        ? <EmptyState title="No projects yet" description="Cross-project counts will appear once projects exist."/>
        : <div className="grid gap-3">{projects.map(project => <ProjectOverviewRow key={project.id} project={project}/>)}</div>}
    </section>

    <section>
      <h2 className="mb-3 flex items-center gap-2 text-lg font-black text-slate-950"><Activity size={18}/> Cross-project activity</h2>
      {activity.length === 0
        ? <EmptyState title="No activity recorded" description="Audit events across all projects will appear here."/>
        : <div className="grid gap-2">{activity.map(event => <div key={event.id} className="rounded-xl border border-slate-200 bg-white p-3 text-sm">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <strong className="text-slate-900">{event.action}</strong>
              <span className="text-xs text-slate-500">{new Date(event.occurred_at).toLocaleString()}</span>
            </div>
            <p className="mt-1 text-slate-600">{event.actor_name} - {event.reason}</p>
          </div>)}</div>}
    </section>
  </div>;
}
