import { Inbox } from "lucide-react";
import { cn } from "../../utils/cn";

export function EmptyState({ icon, title = "Nothing here yet", description, action, className }) {
  return (
    <div className={cn("grid place-items-center gap-2 rounded-2xl border border-dashed border-slate-200 bg-slate-50/70 px-6 py-10 text-center", className)}>
      <span className="grid size-11 place-items-center rounded-xl bg-white text-slate-500 shadow-sm">{icon || <Inbox aria-hidden="true" size={20} />}</span>
      <strong className="text-sm text-slate-900">{title}</strong>
      {description && <p className="m-0 max-w-md text-sm leading-6 text-slate-500">{description}</p>}
      {action}
    </div>
  );
}
