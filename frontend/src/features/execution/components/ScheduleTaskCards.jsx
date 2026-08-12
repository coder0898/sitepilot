import { Pill } from "../../../components/ui";

// U12, mobile. The same facts as the desktop timeline without a horizontal
// scroll - a Gantt chart on a phone is a chart nobody reads.

function DayRange({ label, from, to, tone }) {
  if (from == null) return <div className="text-slate-400">{label}: not started</div>;
  return <div className={tone}>
    {label}: day {from}{to != null && to !== from ? ` to ${to}` : ""}
  </div>;
}

export function ScheduleTaskCards({ rows }) {
  return <ul className="grid list-none gap-2 p-0">
    {rows.map(row => (
      <li key={row.id} className="rounded-xl border border-slate-200 bg-white px-4 py-3">
        <div className="flex flex-wrap items-center gap-2">
          <span className="text-xs font-black text-blue-700">{row.code}</span>
          <strong className="text-sm text-slate-900">{row.title}</strong>
          {row.isEarly && <Pill tone="violet">Started early</Pill>}
        </div>
        <div className="mt-1.5 grid gap-0.5 text-xs">
          <DayRange label="Baseline" from={row.baselineStart} to={row.baselineEnd} tone="text-slate-500"/>
          <DayRange label="Actual" from={row.actualStart} to={row.actualEnd} tone="text-slate-700 font-bold"/>
          {row.isUnfinished && <div className="text-slate-400">Still running</div>}
        </div>
        {row.earlyStartReason && <p className="mt-1.5 text-xs text-violet-700">{row.earlyStartReason}</p>}
      </li>
    ))}
  </ul>;
}
