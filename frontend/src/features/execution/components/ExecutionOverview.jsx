import { CircleDot, Plus, RotateCcw } from "lucide-react";
import { Button, Pill } from "../../../components/ui";
import { deliveryTone } from "../executionPresentation";

const deliveryStatuses = ["all", "scheduled", "sending", "sent", "delivered", "failed"];
const prettyStatus = value => String(value || "assigned").replaceAll("_", " ");

export function NotificationDeliveryHistory({ notifications, filter, setFilter, canRetry, retry }) {
  const visible = notifications.filter(note => filter === "all" || note.status === filter).sort((a, b) => new Date(b.created_at) - new Date(a.created_at));
  return (
    <section className="rounded-[18px] border border-slate-200 bg-white p-4 shadow-[0_14px_35px_rgba(15,23,42,0.06)] md:p-5">
      <header className="flex flex-col gap-4 border-b border-slate-200 pb-4 lg:flex-row lg:items-center lg:justify-between">
        <div><p className="m-0 text-[11px] font-black uppercase tracking-[0.14em] text-blue-700">Mock provider audit</p><h3 className="mt-1 font-serif text-2xl text-slate-950">Notification Delivery History</h3><p className="mt-1 text-sm text-slate-500">No real WhatsApp messages are sent. Every mock attempt remains auditable.</p></div>
        <div className="flex max-w-full gap-2 overflow-x-auto pb-1" aria-label="Filter notification delivery history">
          {deliveryStatuses.map(status => <Button type="button" size="sm" variant={filter === status ? "primary" : "secondary"} key={status} onClick={() => setFilter(status)} className="shrink-0 rounded-full capitalize">{status}</Button>)}
        </div>
      </header>
      <div className="mt-4 grid gap-3 xl:grid-cols-2">
        {visible.map(note => (
          <article key={note.id} className="rounded-2xl border border-slate-200 bg-slate-50/70 p-4">
            <div className="flex flex-wrap items-start justify-between gap-3"><div className="min-w-0"><strong className="block truncate text-sm text-slate-950">{note.taskTitle}</strong><p className="mt-1 text-sm text-slate-600">{note.recipient_name} - {note.recipient_type.replaceAll("_", " ")}</p></div><Pill tone={deliveryTone(note.status)}>{note.status}</Pill></div>
            <div className="mt-3 grid grid-cols-2 gap-2 text-xs text-slate-500"><span>Type: <b className="text-slate-700">{note.notification_type.replaceAll("_", " ")}</b></span><span>Attempts: <b className="text-slate-700">{note.attempt_count}/{note.max_attempts}</b></span><span className="col-span-2">{note.delivered_at ? `Delivered ${new Date(note.delivered_at).toLocaleString("en-GB")}` : note.next_attempt_at ? `Next attempt ${new Date(note.next_attempt_at).toLocaleString("en-GB")}` : note.scheduled_for ? `Scheduled ${new Date(note.scheduled_for).toLocaleString("en-GB")}` : "Queued immediately"}</span></div>
            {note.failure_reason && <p className="mt-3 rounded-xl border border-rose-200 bg-rose-50 p-3 text-xs font-bold text-rose-700">{note.failure_reason}</p>}
            {note.attempts?.length > 0 && <details className="mt-3 rounded-xl border border-slate-200 bg-white p-3"><summary className="cursor-pointer text-xs font-black text-slate-700">View {note.attempts.length} delivery attempt{note.attempts.length === 1 ? "" : "s"}</summary><div className="mt-3 grid gap-2">{note.attempts.map(attempt => <div key={attempt.id} className="flex flex-wrap items-center justify-between gap-2 border-t border-slate-100 pt-2 text-xs"><span>Attempt {attempt.attempt_no} - {new Date(attempt.started_at).toLocaleString("en-GB")}</span><Pill tone={deliveryTone(attempt.status)}>{attempt.status}</Pill>{attempt.failure_reason && <span className="w-full text-rose-700">{attempt.failure_reason}</span>}</div>)}</div></details>}
            {canRetry && note.status === "failed" && note.phone && !note.failure_reason?.startsWith("Superseded") && <Button type="button" size="sm" onClick={() => retry(note.id)} className="mt-3"><RotateCcw size={15} /> Retry with mock sender</Button>}
          </article>
        ))}
        {!visible.length && <div className="xl:col-span-2"><EmptySmall text="No notifications match this status." /></div>}
      </div>
    </section>
  );
}

const metricTones = {
  blue: "[&>div>span]:bg-blue-50 [&>div>span]:text-blue-700",
  orange: "[&>div>span]:bg-amber-50 [&>div>span]:text-amber-700",
  red: "[&>div>span]:bg-rose-50 [&>div>span]:text-rose-700 [&>p]:text-rose-600",
  green: "[&>div>span]:bg-emerald-50 [&>div>span]:text-emerald-700",
  violet: "[&>div>span]:bg-violet-50 [&>div>span]:text-violet-700",
};

export function ExecutionMetric({ icon, label, value, helper, tone, progress }) {
  return <article className={`min-w-0 rounded-2xl border border-slate-200 bg-white p-4 shadow-[0_10px_28px_rgba(27,47,76,0.065)] [&>div]:flex [&>div]:items-center [&>div]:gap-2 [&>div>span]:grid [&>div>span]:size-9 [&>div>span]:place-items-center [&>div>span]:rounded-xl [&>strong]:mt-3 [&>strong]:block [&>strong]:font-serif [&>strong]:text-3xl [&>p]:m-0 [&>p]:mt-1 [&>p]:text-xs [&>p]:font-black [&>p]:text-emerald-600 [&>i]:mt-3 [&>i]:block [&>i]:h-1.5 [&>i]:overflow-hidden [&>i]:rounded-full [&>i]:bg-slate-200 [&>i>b]:block [&>i>b]:h-full [&>i>b]:rounded-full [&>i>b]:bg-emerald-500 ${metricTones[tone] || metricTones.blue}`}><div><span>{icon}</span><small>{label}</small></div><strong>{value}</strong><p>{helper}</p>{progress !== undefined && <i><b style={{ width: `${progress}%` }} /></i>}</article>;
}

export function DayColumn({ day, tasks, canManage, add, select }) {
  return <article className="min-w-0 border-r border-slate-200 last:border-0 max-[720px]:rounded-2xl max-[720px]:border">
    <header className="grid place-items-center p-3 text-center"><small className="font-black text-slate-600">Day {day.day_no}</small><strong className="text-xs">{new Date(day.scheduled_date + "T00:00:00").toLocaleDateString("en-GB", { day: "2-digit", month: "short" })}</strong></header>
    <div className="grid gap-2 px-2 pb-3">
      {tasks.map(task => <button type="button" className={`grid min-h-16 grid-cols-[8px_minmax(0,1fr)_auto] items-center gap-2 rounded-xl border border-slate-200 bg-slate-50 p-3 text-left text-slate-900 ${task.is_overdue ? "!border-rose-300 !bg-rose-50" : task.rescheduled_date ? "!border-amber-300 !bg-amber-50" : ""}`} key={task.id} onClick={() => select(task)}>
        <span className={`size-1.5 rounded-full ${task.is_overdue || task.priority === "high" ? "bg-rose-500" : task.priority === "low" ? "bg-emerald-500" : "bg-blue-500"}`} />
        <div className="grid min-w-0 gap-1"><strong className="truncate text-xs">{task.title}</strong><small className="truncate text-[10px] text-slate-500">{task.subcontractor_name || task.contractor_name || "Internal task"}</small>{task.rescheduled_date && <small className="truncate text-[10px] font-bold text-amber-700">Revised · {new Date(task.rescheduled_date + "T00:00:00").toLocaleDateString("en-GB", { day: "2-digit", month: "short" })}</small>}</div>
        <Pill tone={task.is_overdue ? "red" : task.status === "completed" ? "green" : task.priority === "high" ? "orange" : "blue"}>{task.is_overdue ? `Overdue ${task.overdue_days}d` : prettyStatus(task.status)}</Pill>
      </button>)}
      {canManage && <button type="button" className="flex min-h-11 items-center justify-center gap-2 rounded-xl border border-dashed border-blue-300 bg-white font-black text-blue-700" onClick={add}><Plus /> Add task</button>}
      {!tasks.length && !canManage && <EmptySmall text="No tasks planned" />}
    </div>
  </article>;
}
export function TeamMember({ icon, name, role, phone }) {
  return <article><span>{icon}</span><div><strong>{name}</strong><small>{role}</small><p>{phone || "Phone not added"}</p></div></article>;
}

export function EmptySmall({ text }) {
  return <div className="exec-empty-small grid place-items-center gap-2 p-7 text-center text-xs text-slate-400 [&_svg]:size-5"><CircleDot /><span>{text}</span></div>;
}
