import { CircleAlert, CirclePlay, Info, LockKeyhole } from "lucide-react";
import { EmptyState, Pill } from "../../../components/ui";

// U8: what can start now, and for everything else, what is holding it up.
//
// Advisory. Nothing here starts a task - the board's own controls do that,
// and they are unchanged. This panel exists because the portal could show
// a task as "planned" without ever saying why it was still planned.

const REASON_ICON = {
  predecessor: LockKeyhole,
  gate: LockKeyhole,
  excluded_predecessor: Info,
  unresolved_gate: Info,
};

function Reason({ reason }) {
  const Icon = REASON_ICON[reason.kind] || CircleAlert;
  return <li className={`flex items-start gap-2 text-sm ${reason.enforced ? "text-slate-600" : "text-slate-500"}`}>
    <Icon size={15} className={`mt-0.5 shrink-0 ${reason.enforced ? "text-slate-400" : "text-amber-500"}`}/>
    <span>
      {reason.detail}
      {!reason.enforced && <em className="ml-1 not-italic font-bold text-amber-700">Advisory</em>}
    </span>
  </li>;
}

function TaskRow({ item }) {
  return <div className="rounded-xl border border-slate-200 bg-white px-4 py-3">
    <div className="flex flex-wrap items-center gap-2">
      <span className="text-xs font-black text-blue-700">{item.original_code}</span>
      <strong className="text-sm text-slate-900">{item.title}</strong>
      <Pill tone={item.startable ? "green" : "orange"}>{item.startable ? "Can start" : "Blocked"}</Pill>
      {item.guard_diverges && <Pill tone="gray">Overlap not yet enforced</Pill>}
    </div>
    {item.guard_diverges && <p className="mt-1 text-xs text-slate-500">
      Its predecessor has started, which the schedule treats as enough to begin. The portal still
      asks for that predecessor to be finished before this task can move.
    </p>}
    {item.reasons.length > 0 && <ul className="mt-2 grid list-none gap-1.5 p-0">
      {item.reasons.map((reason, index) => <Reason key={`${reason.kind}-${reason.code}-${index}`} reason={reason}/>)}
    </ul>}
  </div>;
}

export function TaskReadinessPanel({ readiness, loading, error }) {
  if (loading) return <div className="rounded-2xl border border-slate-200 bg-white p-5 text-sm text-slate-500">Working out what can start...</div>;
  // A failed readiness fetch must not blank the rest of the tab - the
  // board below it is the part people actually work from.
  if (error) return <div className="rounded-2xl border border-amber-200 bg-amber-50 p-4 text-sm font-bold text-amber-800">{error}</div>;
  if (!readiness) return null;

  const startable = readiness.items.filter(item => item.startable);
  const blocked = readiness.items.filter(item => !item.startable && item.reasons.length > 0);

  return <div className="grid gap-4 rounded-2xl border border-slate-200 bg-white p-5">
    <div>
      <h3 className="m-0 font-serif text-lg text-slate-950">What can start now</h3>
      <p className="mt-1 text-sm text-slate-500">
        Worked out from applicability, task dependencies and external approvals. This is advice - starting
        a task is still done from the board below.
      </p>
    </div>

    {readiness.unresolved_gates.length > 0 && <div className="rounded-xl border border-amber-200 bg-amber-50 p-3">
      <strong className="text-sm text-amber-900">Approvals that cover no task</strong>
      <ul className="mt-1.5 grid list-none gap-1 p-0">
        {readiness.unresolved_gates.map(gate => <li key={gate.code} className="text-sm text-amber-800">
          <span className="font-black">{gate.code}</span> {gate.detail}
        </li>)}
      </ul>
    </div>}

    <section>
      <div className="flex items-center gap-2 text-xs font-black uppercase tracking-wide text-slate-500">
        <CirclePlay size={15}/> Ready to start ({startable.length})
      </div>
      {startable.length ? (
        <div className="mt-2 grid gap-2">{startable.map(item => <TaskRow key={item.task_id} item={item}/>)}</div>
      ) : (
        <div className="mt-2"><EmptyState title="Nothing can start right now" description="Every remaining task is waiting on a predecessor or an external approval."/></div>
      )}
    </section>

    {blocked.length > 0 && <section>
      <div className="flex items-center gap-2 text-xs font-black uppercase tracking-wide text-slate-500">
        <LockKeyhole size={15}/> Waiting ({blocked.length})
      </div>
      <div className="mt-2 grid gap-2">{blocked.map(item => <TaskRow key={item.task_id} item={item}/>)}</div>
    </section>}
  </div>;
}
