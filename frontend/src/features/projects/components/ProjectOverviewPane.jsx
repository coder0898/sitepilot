import { CircleAlert, Lock, MapPin } from "lucide-react";
import { Pill } from "../../../components/ui";

const longDate = value => (value
  ? new Date(`${value}T00:00:00`).toLocaleDateString("en-GB", { day: "2-digit", month: "short", year: "numeric" })
  : null);

const severityTone = { critical: "red", warning: "orange", decision: "blue" };

function ProgressRing({ pct }) {
  const radius = 33;
  const circumference = 2 * Math.PI * radius;
  return <div className="relative size-[78px] shrink-0">
    <svg viewBox="0 0 78 78" className="size-[78px] -rotate-90" aria-hidden="true">
      <circle cx="39" cy="39" r={radius} fill="none" stroke="#f1f5f9" strokeWidth="8"/>
      <circle cx="39" cy="39" r={radius} fill="none" stroke="#2563eb" strokeWidth="8" strokeLinecap="round"
        strokeDasharray={circumference} strokeDashoffset={circumference * (1 - pct / 100)}/>
    </svg>
    <span className="absolute inset-0 grid place-items-center text-base font-black tabular-nums tracking-tight text-slate-950">{pct}%</span>
  </div>;
}

function PhaseBars({ phases }) {
  return <div className="grid min-w-0 flex-1 gap-1.5">
    {phases.map(phase => <div key={phase.phase} className="grid grid-cols-[7.5rem_minmax(0,1fr)_2.4rem] items-center gap-2 text-xs sm:grid-cols-[9rem_minmax(0,1fr)_2.6rem]">
      <span className="truncate font-medium text-slate-600">{phase.phase}</span>
      <span className="h-1.5 overflow-hidden rounded-full bg-slate-100">
        <span className="block h-full rounded-full" style={{ width: `${phase.pct}%`, background: phase.pct === 100 ? "#059669" : "#2563eb" }}/>
      </span>
      <span className="text-right font-mono text-[11px] tabular-nums text-slate-400">{phase.pct}%</span>
    </div>)}
  </div>;
}

function Tile({ label, value, tone }) {
  const toneClass = { bad: "text-rose-700", warn: "text-amber-700", brand: "text-blue-700" }[tone] || "text-slate-950";
  return <div className="rounded-xl border border-slate-200 bg-white p-3">
    <dt className="text-[11px] font-semibold text-slate-500">{label}</dt>
    <dd className={`mt-0.5 text-xl font-black tabular-nums tracking-tight ${value ? toneClass : "text-slate-950"}`}>{value}</dd>
  </div>;
}

export function ProjectOverviewPane({ project, summary, attention = [], onOpenPane }) {
  const handover = longDate(project.target_handover_date);
  const phases = summary?.phases?.length ? summary.phases : null;

  return <div className="grid gap-3">
    {attention.length > 0 && <div className="flex items-center gap-2 rounded-xl border border-amber-200 bg-amber-50 px-3 py-2 text-xs font-bold text-amber-800">
      <CircleAlert size={15} className="shrink-0" aria-hidden="true"/>
      <span className="min-w-0">{attention.map(item => item.title).join(" · ")}</span>
    </div>}

    {summary && <section className="rounded-2xl border border-slate-200 bg-white p-4 sm:p-5">
      <div className="flex items-baseline justify-between gap-3">
        <div>
          <h3 className="text-sm font-black text-slate-950">Execution progress</h3>
          <p className="mt-0.5 text-xs text-slate-500">
            {summary.completed_count} of {summary.total_count} tasks complete{handover ? ` · handover ${handover}` : ""}
          </p>
        </div>
        <button type="button" onClick={() => onOpenPane("template-review")} className="shrink-0 text-xs font-black text-blue-700 hover:underline">All tasks</button>
      </div>
      <div className="mt-4 flex flex-col items-start gap-4 sm:flex-row sm:items-center">
        <ProgressRing pct={summary.progress_pct ?? 0}/>
        {phases ? <PhaseBars phases={phases}/> : <p className="text-xs text-slate-400">Phase breakdown is not available for this project.</p>}
      </div>
    </section>}

    {summary && <dl className="grid gap-2 sm:grid-cols-2 lg:grid-cols-4">
      <Tile label="Pending approvals" value={summary.pending_approvals ?? 0} tone="brand"/>
      <Tile label="Blocked" value={summary.blocked_count ?? 0} tone="bad"/>
      <Tile label="Delayed" value={summary.delayed_count ?? 0} tone="warn"/>
      <Tile label="No update 48h" value={summary.no_update_count ?? 0}/>
    </dl>}

    {attention.length > 0 && <section className="rounded-2xl border border-slate-200 bg-white p-4 sm:p-5">
      <h3 className="text-sm font-black text-slate-950">Waiting on you</h3>
      <div className="mt-2 grid">
        {attention.map(item => <div key={item.id} className="flex items-center justify-between gap-3 border-b border-slate-100 py-2.5 last:border-0">
          <div className="min-w-0">
            <strong className="block truncate text-sm font-semibold text-slate-900">{item.title}</strong>
            <span className="block truncate text-[11px] text-slate-400">{item.subtitle}</span>
          </div>
          <Pill tone={severityTone[item.severity] || "orange"}>{item.due_label || "Open"}</Pill>
        </div>)}
      </div>
    </section>}

    <section className="rounded-2xl border border-slate-200 bg-white p-4 sm:p-5">
      <div className="flex items-start gap-3">
        <span className="grid size-10 shrink-0 place-items-center rounded-xl bg-blue-50 text-blue-700"><MapPin size={18} aria-hidden="true"/></span>
        <div className="min-w-0">
          <h3 className="text-sm font-black text-slate-950">Site brief</h3>
          <p className="mt-1 whitespace-pre-wrap text-sm leading-6 text-slate-600">{project.site_address}</p>
          {project.description && <p className="mt-3 border-t border-slate-100 pt-3 text-sm leading-6 text-slate-500">{project.description}</p>}
        </div>
      </div>
      <dl className="mt-4 grid gap-3 border-t border-slate-100 pt-4 sm:grid-cols-3">
        {[["Start date", longDate(project.start_date)], ["Target handover", handover || "Not set"], ["Client", project.client_name]]
          .map(([label, value]) => <div key={label}>
            <dt className="font-mono text-[10px] uppercase tracking-[.1em] text-slate-400">{label}</dt>
            <dd className="mt-0.5 text-sm font-semibold text-slate-900">{value}</dd>
          </div>)}
      </dl>
    </section>

    {project.status !== "draft" && <p className="flex items-center gap-2 rounded-xl border border-dashed border-slate-200 bg-slate-50 px-3 py-2.5 text-xs text-slate-500">
      <Lock size={14} className="shrink-0 text-slate-400" aria-hidden="true"/>
      Baseline locked on activation. The template reference can no longer change.
    </p>}
  </div>;
}
