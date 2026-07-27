import { CheckCircle2, ChevronRight } from "lucide-react";
import { Button, Pill, Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "../../../components/ui";
import { formatTemplateDate, statusTone } from "./TemplateCard";

export function TemplateTable({ items, selectedTemplateVersionId, onSelect }) {
  return <div className="hidden overflow-hidden rounded-[22px] border border-slate-200 bg-white shadow-[0_14px_44px_rgba(15,23,42,.05)] lg:block">
    <Table>
      <TableHead><TableRow className="hover:bg-transparent"><TableHeader>Template</TableHeader><TableHeader>Version</TableHeader><TableHeader>Status</TableHeader><TableHeader>Duration</TableHeader><TableHeader className="text-center">Tasks</TableHeader><TableHeader className="text-center">Dependencies</TableHeader><TableHeader className="text-center">Gates</TableHeader><TableHeader>Published</TableHeader><TableHeader className="text-right">Action</TableHeader></TableRow></TableHead>
      <TableBody>{items.map(item => {
        const selected = selectedTemplateVersionId === item.version_id;
        return <TableRow key={item.version_id} data-selected={selected || undefined} className={selected ? "bg-blue-50/70 hover:bg-blue-50/70" : ""}>
          <TableCell><div className="max-w-[280px]"><strong className="block truncate font-black text-slate-950">{item.template_name}</strong><span className="mt-1 block font-mono text-[11px] font-bold uppercase tracking-wide text-slate-400">{item.template_code}</span></div></TableCell>
          <TableCell><div className="flex items-center gap-2"><strong>v{item.version_no}</strong>{item.is_current_published && <span title="Current published version" className="text-emerald-600"><CheckCircle2 size={16}/></span>}</div></TableCell>
          <TableCell><Pill tone={statusTone(item.status)}>{item.status}</Pill></TableCell>
          <TableCell>{item.duration_days} days</TableCell><TableCell className="text-center font-black text-slate-900">{item.task_count}</TableCell><TableCell className="text-center font-black text-slate-900">{item.dependency_count}</TableCell><TableCell className="text-center font-black text-slate-900">{item.gate_count}</TableCell><TableCell className="whitespace-nowrap">{formatTemplateDate(item.published_at)}</TableCell>
          <TableCell className="text-right"><Button size="sm" variant="ghost" aria-pressed={selected} onClick={() => onSelect(item.version_id)}>View Details <ChevronRight size={15}/></Button></TableCell>
        </TableRow>;
      })}</TableBody>
    </Table>
  </div>;
}