import { cn } from "../../utils/cn";
export function Table({ children, className }) { return <div className="w-full overflow-x-auto"><table className={cn("w-full border-collapse text-left text-sm", className)}>{children}</table></div>; }
export function TableHead({ children, className }) { return <thead className={cn("border-b border-slate-200 bg-slate-50/80 text-xs font-extrabold uppercase tracking-wider text-slate-500", className)}>{children}</thead>; }
export function TableBody({ children, className }) { return <tbody className={cn("divide-y divide-slate-100", className)}>{children}</tbody>; }
export function TableRow({ children, className, ...props }) { return <tr className={cn("transition-colors hover:bg-slate-50/80", className)} {...props}>{children}</tr>; }
export function TableHeader({ children, className, ...props }) { return <th className={cn("px-5 py-3.5", className)} {...props}>{children}</th>; }
export function TableCell({ children, className, ...props }) { return <td className={cn("px-5 py-4 text-slate-700", className)} {...props}>{children}</td>; }
