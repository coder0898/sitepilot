import { cn } from "../../utils/cn";

export function FormGrid({ children, className }) {
  return <div className={cn("grid grid-cols-1 gap-4 md:grid-cols-2", className)}>{children}</div>;
}

export function FormSection({ title, description, icon: Icon, children, className }) {
  return <section className={cn("overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-[0_12px_35px_rgba(15,23,42,.05)]", className)}><header className="flex items-start gap-3 border-b border-slate-100 px-4 py-4 sm:px-5">{Icon && <span className="grid size-10 shrink-0 place-items-center rounded-xl bg-blue-50 text-blue-700"><Icon size={18}/></span>}<div><h3 className="font-black text-slate-950">{title}</h3>{description && <p className="mt-1 text-xs leading-5 text-slate-500">{description}</p>}</div></header><div className="p-4 sm:p-5">{children}</div></section>;
}

export function DetailGrid({ items, className }) {
  return <div className={cn("grid grid-cols-1 gap-px overflow-hidden rounded-2xl border border-slate-200 bg-slate-200 sm:grid-cols-2", className)}>{items.map(({ label, value }) => <article key={label} className="min-w-0 bg-white p-4"><span className="block text-[10px] font-black uppercase tracking-[.16em] text-slate-400">{label}</span><strong className="mt-2 block break-words text-sm leading-6 text-slate-800">{value || "Not provided"}</strong></article>)}</div>;
}