import { LoaderCircle } from "lucide-react";
import { cn } from "../../utils/cn";

export function LoadingSpinner({ label = "Loading", className }) {
  return <span role="status" className={cn("inline-flex items-center gap-2 text-sm font-semibold text-slate-600", className)}><LoaderCircle aria-hidden="true" className="animate-spin" size={18} /><span>{label}</span></span>;
}
