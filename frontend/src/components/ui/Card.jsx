import { cn } from "../../utils/cn";
export function Card({ children, className }) { return <section className={cn("rounded-2xl border border-slate-200 bg-white p-5 shadow-[0_12px_40px_rgba(15,23,42,0.06)]", className)}>{children}</section>; }
