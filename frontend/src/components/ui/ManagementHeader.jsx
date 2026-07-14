import { Button } from "./Button";
export function ManagementHeader({ eyebrow, title, subtitle, actionLabel, actionIcon, onAction }) {
  return <section className="flex flex-col gap-5 rounded-2xl border border-slate-200 bg-white p-6 shadow-[0_12px_40px_rgba(15,23,42,0.06)] sm:flex-row sm:items-center sm:justify-between"><div><p className="text-xs font-black uppercase tracking-[0.18em] text-blue-700">{eyebrow}</p><h2 className="mt-2 text-3xl font-black tracking-tight text-slate-950">{title}</h2><span className="mt-2 block text-sm leading-6 text-slate-500">{subtitle}</span></div>{actionLabel && <Button size="lg" onClick={onAction}>{actionIcon}{actionLabel}</Button>}</section>;
}
