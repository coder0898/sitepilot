import { RefreshCw } from "lucide-react";
import { Button } from "./Button";

export function RefreshButton({ loading = false, children = "Refresh", ...props }) {
  return <Button variant="secondary" loading={loading} {...props}>{!loading && <RefreshCw aria-hidden="true" size={18} />}{children}</Button>;
}
