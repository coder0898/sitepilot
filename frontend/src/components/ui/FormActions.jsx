import { cn } from "../../utils/cn";

export function FormActions({ children, className }) {
  return <div className={cn("flex flex-col-reverse gap-3 sm:flex-row sm:justify-end", className)}>{children}</div>;
}
