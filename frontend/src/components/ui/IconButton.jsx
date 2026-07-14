import { Button } from "./Button";

const iconSizes = { sm: "!size-9 !rounded-lg", md: "!size-11", lg: "!size-13" };

export function IconButton({ children, size = "md", "aria-label": ariaLabel, title, className = "", ...props }) {
  if (!ariaLabel) throw new Error("IconButton requires an aria-label");
  return <Button size="icon" aria-label={ariaLabel} title={title || ariaLabel} className={`${iconSizes[size] || iconSizes.md} ${className}`.trim()} {...props}>{children}</Button>;
}
