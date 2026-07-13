import { cn } from "../../utils/cn";

const variants = {
  primary: "bg-blue-700 text-white shadow-sm hover:bg-blue-800 focus-visible:outline-blue-700",
  secondary: "border border-slate-200 bg-white text-slate-700 shadow-sm hover:bg-slate-50 focus-visible:outline-slate-500",
  ghost: "bg-transparent text-slate-600 hover:bg-slate-100 hover:text-slate-950 focus-visible:outline-slate-500",
  danger: "border border-rose-200 bg-rose-50 text-rose-700 hover:bg-rose-100 focus-visible:outline-rose-600",
};
const sizes = { sm: "min-h-9 rounded-lg px-3 text-sm", md: "min-h-11 rounded-xl px-4 text-sm", lg: "min-h-13 rounded-xl px-5 text-base", icon: "size-11 rounded-xl p-0" };
export function Button({ as: Component = "button", variant = "primary", size = "md", className, type, children, ...props }) {
  return <Component type={Component === "button" ? (type || "button") : type} className={cn("inline-flex shrink-0 items-center justify-center gap-2 font-bold transition focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 disabled:pointer-events-none disabled:opacity-50", variants[variant], sizes[size], className)} {...props}>{children}</Component>;
}
