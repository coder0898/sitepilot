import { cn } from "../../utils/cn";
const controlClass = "min-h-11 w-full rounded-xl border border-slate-200 bg-white px-3.5 py-2.5 text-sm text-slate-950 shadow-sm outline-none transition placeholder:text-slate-400 focus:border-blue-600 focus:ring-4 focus:ring-blue-600/10 disabled:cursor-not-allowed disabled:bg-slate-50 disabled:text-slate-500";
export function Field({ label, hint, error, className, children }) { return <label className={cn("grid gap-2 text-sm font-bold text-slate-700", className)}><span>{label}</span>{children}{(error || hint) && <small className={cn("font-medium", error ? "text-rose-600" : "text-slate-500")}>{error || hint}</small>}</label>; }
export function Input({ className, ...props }) { return <input className={cn(controlClass, className)} {...props} />; }
export function Select({ className, children, ...props }) { return <select className={cn(controlClass, "appearance-auto", className)} {...props}>{children}</select>; }
export function Textarea({ className, ...props }) { return <textarea className={cn(controlClass, "min-h-24 resize-y", className)} {...props} />; }
