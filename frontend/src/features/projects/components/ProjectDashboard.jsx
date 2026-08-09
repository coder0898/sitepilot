import { useEffect, useState } from "react";
import { AlertTriangle, CheckCircle2, Clock3, ShieldAlert, Truck, UserX } from "lucide-react";
import { projectsApi } from "../../../api/projectsApi";
import { EmptyState, LoadingSpinner, Pill } from "../../../components/ui";

// Phase 3 U2: read-only summary view over U1's ProjectVisibilityService.
// Renders whatever the dashboard endpoint returns - it does not derive any
// of its own counts, per the plan's "single source of truth" decision.

function StatTile({ label, value, tone = "slate" }) {
  const toneClasses = {
    slate: "border-slate-200 bg-white text-slate-950",
    amber: "border-amber-300 bg-amber-50 text-amber-950",
    rose: "border-rose-300 bg-rose-50 text-rose-950",
    emerald: "border-emerald-300 bg-emerald-50 text-emerald-950",
  };
  return <div className={`rounded-2xl border p-4 ${toneClasses[tone]}`}>
    <p className="text-[10px] font-black uppercase tracking-[.14em] opacity-70">{label}</p>
    <p className="mt-1 text-2xl font-black">{value}</p>
  </div>;
}

function TaskListCard({ title, icon: Icon, tone, items, renderMeta }) {
  if (!items.length) return null;
  return <div className="rounded-2xl border border-slate-200 bg-white p-4">
    <h3 className="flex items-center gap-2 font-black text-slate-950"><Icon size={16}/> {title} <Pill tone={tone}>{items.length}</Pill></h3>
    <div className="mt-3 grid gap-2">
      {items.map(item => <div key={item.id} className="rounded-xl border border-slate-200 bg-slate-50 p-3 text-sm">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <span className="font-bold text-slate-900">{item.original_code} - {item.title}</span>
          <Pill tone="slate">{item.lifecycle_status.replace("_", " ")}</Pill>
        </div>
        {renderMeta && <p className="mt-1 text-xs text-slate-600">{renderMeta(item)}</p>}
      </div>)}
    </div>
  </div>;
}

export function ProjectDashboard({ project }) {
  const [data, setData] = useState(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);

  async function load() {
    setLoading(true);
    setError("");
    try {
      setData(await projectsApi.dashboard(project.id));
    } catch (caught) {
      setError(caught?.message || "The dashboard could not be loaded.");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => { load(); }, [project.id]);

  if (loading) return <div className="grid min-h-32 place-items-center"><LoadingSpinner label="Loading dashboard..."/></div>;
  if (error) return <div className="rounded-xl border border-rose-200 bg-rose-50 p-3 text-sm font-bold text-rose-700">{error}</div>;
  if (!data) return null;

  const { summary, vendor_risks: vendorRisks } = data;

  return <div className="grid gap-4">
    <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
      <StatTile label="Planned" value={summary.planned_count}/>
      <StatTile label="Active" value={summary.active_count}/>
      <StatTile label="Completed" value={summary.completed_count} tone="emerald"/>
      <StatTile label="Total" value={summary.total_count}/>
    </div>

    <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
      <StatTile label="Blocked" value={summary.blocked_tasks.length} tone={summary.blocked_tasks.length ? "rose" : "slate"}/>
      <StatTile label="Delayed" value={summary.delayed_tasks.length} tone={summary.delayed_tasks.length ? "amber" : "slate"}/>
      <StatTile label="Overdue" value={summary.overdue_tasks.length} tone={summary.overdue_tasks.length ? "rose" : "slate"}/>
      <StatTile label="No update" value={summary.no_update_tasks.length} tone={summary.no_update_tasks.length ? "amber" : "slate"}/>
    </div>

    <TaskListCard title="Pending verifications" icon={Clock3} tone="amber" items={summary.pending_verifications}/>
    <TaskListCard title="Pending approvals" icon={Clock3} tone="amber" items={summary.pending_approvals}/>
    <TaskListCard
      title="Approval gates at risk" icon={ShieldAlert} tone="rose" items={summary.approval_gates_at_risk}
      renderMeta={item => item.due_at ? `Due ${new Date(item.due_at).toLocaleDateString()}` : null}
    />
    <TaskListCard
      title="Overdue tasks" icon={AlertTriangle} tone="rose" items={summary.overdue_tasks}
      renderMeta={item => `Due ${new Date(item.due_at).toLocaleDateString()}`}
    />
    <TaskListCard
      title="No recent update" icon={Clock3} tone="amber" items={summary.no_update_tasks}
      renderMeta={item => `Last activity ${new Date(item.last_activity_at).toLocaleDateString()} (SLA ${item.update_sla_hours}h)`}
    />

    {summary.reassignment_required.length > 0 && <div className="rounded-2xl border border-amber-300 bg-amber-50 p-4">
      <h3 className="flex items-center gap-2 font-black text-amber-950"><UserX size={16}/> Reassignment required <Pill tone="orange">{summary.reassignment_required.length}</Pill></h3>
      <div className="mt-2 grid gap-1">
        {summary.reassignment_required.map(item => <p key={item.membership_id} className="text-sm text-amber-900">
          The active <strong>{item.role_type.replace("_", " ")}</strong> is marked unavailable.
        </p>)}
      </div>
    </div>}

    <div className="rounded-2xl border border-slate-200 bg-white p-4">
      <h3 className="flex items-center gap-2 font-black text-slate-950"><Truck size={16}/> Vendor risks <Pill tone={vendorRisks.length ? "rose" : "slate"}>{vendorRisks.length}</Pill></h3>
      {vendorRisks.length === 0
        ? <EmptyState title="No vendor risks recorded" description="Delay, rework, and incident events logged against this project's vendors will appear here."/>
        : <div className="mt-3 grid gap-2">{vendorRisks.map(item => <div key={item.id} className="rounded-xl border border-slate-200 bg-slate-50 p-3 text-sm">
            <div className="flex items-center justify-between gap-2"><Pill tone="rose">{item.event_type}</Pill><span className="text-xs text-slate-500">{new Date(item.created_at).toLocaleDateString()}</span></div>
            <p className="mt-1 text-slate-700">{item.description}</p>
          </div>)}</div>}
    </div>

    {summary.total_count === 0 && <EmptyState icon={<CheckCircle2 size={20}/>} title="No execution tasks yet" description="This project has not generated execution tasks - counts will populate once it is activated."/>}
  </div>;
}
