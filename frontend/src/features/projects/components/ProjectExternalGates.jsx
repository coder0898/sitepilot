import { Check, Plus, RotateCcw, ShieldCheck } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { projectsApi } from "../../../api/projectsApi";
import { Button, EmptyState, Pill } from "../../../components/ui";
import { GateApplicabilityControls } from "./GateApplicabilityDecisionModal";
import { ProjectManualGateModal } from "./ProjectManualGateModal";

const mappingLabel = { exact: "Exact", broad_text: "Broad text", unmapped: "Unmapped" };

export function ProjectExternalGates({ project, user }) {
  const [data, setData] = useState({ total: 0, items: [] });
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [confirmed, setConfirmed] = useState(false);
  const [error, setError] = useState("");
  const [showManual, setShowManual] = useState(false);
  const requestRef = useRef(false);
  const canGenerate = ["admin", "super_admin"].includes(user.role) && project.status === "draft";
  const canDecide = ["admin", "project_manager"].includes(user.role) && project.status === "draft";
  const canAddManual = canDecide;

  async function load() {
    setLoading(true); setError("");
    try { setData(await projectsApi.externalGates(project.id)); }
    catch (caught) { setError(caught?.message || "Unable to load project gates."); }
    finally { setLoading(false); }
  }
  useEffect(() => { load(); }, [project.id]);

  async function generate() {
    if (!canGenerate || !confirmed || busy || requestRef.current) return;
    requestRef.current = true; setBusy(true); setError("");
    try { await projectsApi.generateGates(project.id); setConfirmed(false); await load(); }
    catch (caught) { setError(caught?.message || "Unable to generate project gates."); }
    finally { requestRef.current = false; setBusy(false); }
  }

  return <div className="grid gap-4">
    <section className="rounded-2xl border border-slate-200 bg-white p-4 sm:p-5">
      <div className="flex flex-wrap items-start justify-between gap-3"><div className="flex items-start gap-3"><span className="grid size-10 shrink-0 place-items-center rounded-xl bg-amber-50 text-amber-700"><ShieldCheck size={18}/></span><div><h3 className="font-black text-slate-950">Project external gates</h3><p className="mt-1 text-xs leading-5 text-slate-500">Separate draft approval records copied from the selected published template.</p></div></div><div className="flex flex-wrap items-center gap-2"><Pill tone="blue">{data.total} gates</Pill>{canAddManual && !showManual && <Button variant="secondary" onClick={() => setShowManual(true)}><Plus size={15}/> Add manual approval</Button>}</div></div>
    </section>
    {error && <div role="alert" className="rounded-xl border border-rose-200 bg-rose-50 p-3 text-sm font-bold text-rose-700">{error}<Button variant="secondary" className="ml-3" onClick={load}><RotateCcw size={15}/> Retry</Button></div>}
    {loading ? <div className="rounded-2xl border border-slate-200 bg-white p-6 text-sm font-bold text-slate-500">Loading external gates...</div> : data.total === 0 ? <>
      <EmptyState icon={<ShieldCheck size={20}/>} title="No project gates generated" description="Generate the project-owned gate snapshot after project tasks exist."/>
      {canGenerate && <section className="rounded-2xl border border-blue-200 bg-blue-50/60 p-4 sm:p-5"><label className="flex items-start gap-3 rounded-xl border border-blue-200 bg-white p-3 text-sm text-slate-700"><input type="checkbox" checked={confirmed} disabled={busy} onChange={event => setConfirmed(event.target.checked)} className="mt-0.5 size-4"/><span>I confirm the selected published template is correct. Gates will remain pending review and the project will remain Draft.</span></label><Button className="mt-4 w-full sm:w-auto" disabled={!confirmed || busy} loading={busy} onClick={generate}>Generate gates</Button></section>}
    </> : <div className="grid gap-3">{data.items.map(gate => <article key={gate.id} className="rounded-2xl border border-slate-200 bg-white p-4 sm:p-5"><div className="flex flex-wrap items-start justify-between gap-3"><div className="min-w-0"><div className="flex flex-wrap items-center gap-2"><span className="text-xs font-black text-blue-700">{gate.code}</span><Pill tone="orange">{gate.status.replaceAll("_", " ")}</Pill><Pill tone={gate.applicability_state === "applicable" ? "green" : gate.applicability_state === "not_applicable" ? "red" : "orange"}>{(gate.applicability_state || "pending_review").replaceAll("_", " ")}</Pill><Pill tone="gray">{mappingLabel[gate.mapping_classification]}</Pill></div><h4 className="mt-2 font-black text-slate-950">{gate.approval_name}</h4>{gate.description && <p className="mt-1 text-sm leading-6 text-slate-600">{gate.description}</p>}</div><span className="text-xs font-bold text-slate-400">#{gate.sequence}</span></div><div className="mt-4 grid gap-2 text-xs sm:grid-cols-3"><div className="rounded-xl bg-slate-50 p-3"><span className="block font-black uppercase tracking-wide text-slate-400">Source</span><strong className="mt-1 block text-slate-700">{gate.source === "project_manual" ? "Manual" : "Template"}</strong></div><div className="rounded-xl bg-slate-50 p-3"><span className="block font-black uppercase tracking-wide text-slate-400">PM owner</span><strong className="mt-1 block text-slate-700">{gate.accountable_pm_name}</strong></div><div className="rounded-xl bg-slate-50 p-3"><span className="block font-black uppercase tracking-wide text-slate-400">Mapping</span><strong className="mt-1 block text-slate-700">{gate.mapping_classification === "exact" ? `${gate.exact_task_count} task links` : gate.broad_mapping_text || "Configuration required"}</strong>{gate.blocking && <small className="mt-1 block font-bold text-rose-600">Blocking</small>}</div></div><div className="mt-4 border-t border-slate-100 pt-4"><GateApplicabilityControls projectId={project.id} gate={gate} canDecide={canDecide} onDecided={load}/></div></article>)}</div>}
    {showManual && <ProjectManualGateModal projectId={project.id} onClose={() => setShowManual(false)} onCreated={load}/>}
    {data.total > 0 && <div className="rounded-xl border border-emerald-200 bg-emerald-50 p-3 text-sm font-bold text-emerald-800"><Check className="mr-2 inline" size={16}/>{data.total} gates generated. Retry is idempotent and creates no duplicates.</div>}
  </div>;
}
