import { SlidersHorizontal } from "lucide-react";
import { Button } from "./Button";
import { Card } from "./Card";
import { Input } from "./Field";
import { Pill } from "./Pill";
import { Table } from "./Table";

export function ManagementTable({ countLabel, count, searchPlaceholder, tableClassName = "", mobileContent, children }) {
  return <Card className="overflow-hidden p-0"><div className="flex flex-col gap-3 border-b border-slate-100 p-4 sm:flex-row sm:items-center sm:justify-between sm:p-5"><div className="flex items-center gap-2 text-sm font-extrabold text-slate-700">{countLabel}<Pill>{count}</Pill></div><div className="grid grid-cols-[minmax(0,1fr)_auto] gap-2 sm:flex"><Input className="sm:w-64" placeholder={searchPlaceholder} readOnly/><Button size="icon" variant="secondary" aria-label="Filters"><SlidersHorizontal size={17}/><span className="sr-only">Filters</span></Button></div></div>{mobileContent && <div className="divide-y divide-slate-100 md:hidden">{mobileContent}</div>}<div className={mobileContent ? "hidden md:block" : ""}><Table className={tableClassName}>{children}</Table></div></Card>;
}