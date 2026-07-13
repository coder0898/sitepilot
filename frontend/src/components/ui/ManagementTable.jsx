import { SlidersHorizontal } from "lucide-react";
import { Button } from "./Button";
import { Card } from "./Card";
import { Input } from "./Field";
import { Pill } from "./Pill";
export function ManagementTable({ countLabel, count, searchPlaceholder, tableClassName = "", children }) {
  return <Card className="overflow-hidden p-0"><div className="flex flex-col gap-4 border-b border-slate-100 p-5 sm:flex-row sm:items-center sm:justify-between"><div className="flex items-center gap-2 text-sm font-extrabold text-slate-700">{countLabel}<Pill>{count}</Pill></div><div className="flex flex-col gap-2 sm:flex-row"><Input className="sm:w-64" placeholder={searchPlaceholder} readOnly/><Button variant="secondary"><SlidersHorizontal size={17}/>Filters</Button></div></div><div className="overflow-x-auto"><table className={`w-full border-collapse text-left text-sm ${tableClassName}`.trim()}>{children}</table></div></Card>;
}
