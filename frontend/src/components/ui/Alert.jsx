import { CircleAlert, CircleCheck, Info, X } from "lucide-react";
import { cn } from "../../utils/cn";
import { IconButton } from "./IconButton";

const tones = {
  info: { icon: Info, className: "border-blue-200 bg-blue-50 text-blue-950" },
  success: { icon: CircleCheck, className: "border-emerald-200 bg-emerald-50 text-emerald-950" },
  warning: { icon: CircleAlert, className: "border-amber-200 bg-amber-50 text-amber-950" },
  danger: { icon: CircleAlert, className: "border-rose-200 bg-rose-50 text-rose-950" },
};

export function Alert({ children, tone = "info", onDismiss, className, ...props }) {
  const config = tones[tone] || tones.info;
  const Icon = config.icon;
  return (
    <div role={tone === "danger" ? "alert" : "status"} className={cn("flex items-start gap-3 rounded-2xl border px-4 py-3 text-sm font-semibold", config.className, className)} {...props}>
      <Icon aria-hidden="true" className="mt-0.5 shrink-0" size={18} />
      <div className="min-w-0 flex-1">{children}</div>
      {onDismiss && <IconButton aria-label="Dismiss message" title="Dismiss" size="sm" variant="ghost" onClick={onDismiss}><X size={17} /></IconButton>}
    </div>
  );
}
