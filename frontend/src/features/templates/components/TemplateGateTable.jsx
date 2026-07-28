import { AlertTriangle, CheckCircle2 } from "lucide-react";
import { Pill, Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "../../../components/ui";
import { gateMappingLabel, TemplateGateDetails } from "./TemplateGateCard";

export function TemplateGateTable({ gates, onFocusTask }) {
  return <div className="hidden overflow-hidden rounded-2xl border border-slate-200 bg-white lg:block">
    <Table>
      <TableHead><TableRow className="hover:bg-transparent"><TableHeader>Gate</TableHeader><TableHeader>External party</TableHeader><TableHeader>Required by</TableHeader><TableHeader>Mapping</TableHeader><TableHeader>Impact</TableHeader><TableHeader>Validation</TableHeader></TableRow></TableHead>
      <TableBody>{gates.map(gate => {
        const invalid = gate.validation_state === "invalid";
        return <TableRow key={gate.id} data-testid={`gate-row-${gate.id}`} className={invalid ? "bg-amber-50/60 hover:bg-amber-50" : ""}>
          <TableCell className="max-w-[250px] align-top"><span className="font-mono text-[10px] font-black tracking-[.1em] text-blue-700">{gate.code}</span><strong className="mt-1 block text-sm text-slate-950">{gate.approval_name || "Unnamed approval"}</strong><details className="mt-2"><summary className="cursor-pointer text-xs font-black text-blue-700">View details</summary><div className="mt-3 min-w-[420px]"><TemplateGateDetails gate={gate} onFocusTask={onFocusTask}/></div></details></TableCell>
          <TableCell className="max-w-[180px] align-top text-xs font-semibold text-slate-700">{gate.external_party || "-"}</TableCell>
          <TableCell className="max-w-[190px] align-top text-xs font-semibold text-slate-700">{gate.required_by_value || "-"}</TableCell>
          <TableCell className="align-top"><div className="flex flex-col items-start gap-2"><Pill tone={gate.mapping_classification === "exact" ? "blue" : "orange"}>{gateMappingLabel(gate.mapping_classification)}</Pill>{gate.requires_configuration && <span className="text-[10px] font-black text-amber-700">Requires configuration</span>}</div></TableCell>
          <TableCell className="max-w-[240px] align-top text-xs leading-5 text-slate-600">{gate.impact || "-"}</TableCell>
          <TableCell className="align-top"><span className={`inline-flex items-start gap-1.5 text-xs font-black ${invalid ? "text-amber-700" : "text-emerald-700"}`}>{invalid ? <AlertTriangle className="mt-0.5 shrink-0" size={15}/> : <CheckCircle2 className="mt-0.5 shrink-0" size={15}/>}<span>{invalid ? gate.validation_issues.join(", ").replaceAll("_", " ") : "Valid"}</span></span></TableCell>
        </TableRow>;
      })}</TableBody>
    </Table>
  </div>;
}
