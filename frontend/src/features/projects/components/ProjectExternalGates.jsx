import { Check, Plus, RotateCcw, ShieldCheck, X } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { projectsApi } from "../../../api/projectsApi";
import { Button, EmptyState, Field, Modal, Pill, Textarea } from "../../../components/ui";
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
  const [selected, setSelected] = useState(() => new Set());
  const [bulkBusy, setBulkBusy] = useState(false);
  const [bulkError, setBulkError] = useState("");
  const [bulkNotApplicable, setBulkNotApplicable] = useState(false);
  const [bulkReason, setBulkReason] = useState("");
  const requestRef = useRef(false);
  const canGenerate = ["admin", "super_admin"].includes(user.role) && project.status === "draft";
  // Admin decides whether an approval applies; the assigned PM reads it.
  //
  // Draft OR active, mirroring ProjectGateApplicabilityService. Applicability
  // used to be draft-only here and on the backend, while activation never
  // required the gates to have been reviewed - so a project could go live
  // with every gate undecided and then nobody could ever decide them, and
  // since only an APPLICABLE gate becomes a runtime approval, that project
  // could never hold an external approval at all.
  const canDecide = user.role === "admin" && ["draft", "active"].includes(project.status);
  // NOT the same rule: adding a brand-new approval is still draft-only on the
  // backend (`ProjectManualGateService`), so offering it on an active project
  // would render a control that 409s on click.
  const canAddManual = user.role === "admin" && project.status === "draft";

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

  function toggleSelected(gateId) {
    setSelected(previous => {
      const next = new Set(previous);
      if (next.has(gateId)) next.delete(gateId); else next.add(gateId);
      return next;
    });
  }

  function toggleSelectAll() {
    setSelected(previous => previous.size === data.items.length ? new Set() : new Set(data.items.map(gate => gate.id)));
  }

  // Applying the same decision a gate already carries would just append a
  // redundant history entry, so bulk actions skip gates already at the
  // target state instead of re-deciding them.
  async function applyBulkDecision(decision, reason) {
    const targets = data.items.filter(gate => selected.has(gate.id) && gate.applicability_state !== decision);
    if (targets.length === 0) { setSelected(new Set()); setBulkNotApplicable(false); return; }
    setBulkBusy(true); setBulkError("");
    try {
      const results = await Promise.allSettled(
        targets.map(gate => projectsApi.decideGateApplicability(project.id, gate.id, { decision, reason: reason || null })),
      );
      const failed = results.filter(result => result.status === "rejected");
      if (failed.length > 0) {
        setBulkError(`${failed.length} of ${targets.length} gates could not be updated. ${failed[0].reason?.message || ""}`.trim());
      } else {
        setSelected(new Set());
        setBulkNotApplicable(false);
        setBulkReason("");
      }
      await load();
    } finally {
      setBulkBusy(false);
    }
  }

  return <div className="grid gap-4">
    <section className="rounded-2xl border border-slate-200 bg-white p-4 sm:p-5">
      <div className="flex flex-wrap items-start justify-between gap-3"><div className="flex items-start gap-3"><span className="grid size-10 shrink-0 place-items-center rounded-xl bg-amber-50 text-amber-700"><ShieldCheck size={18}/></span><div><h3 className="font-black text-slate-950">Project external gates</h3><p className="mt-1 text-xs leading-5 text-slate-500">Separate draft approval records copied from the selected published template.</p></div></div><div className="flex flex-wrap items-center gap-2"><Pill tone="blue">{data.total} gates</Pill>{canAddManual && !showManual && <Button variant="secondary" onClick={() => setShowManual(true)}><Plus size={15}/> Add manual approval</Button>}</div></div>
    </section>
    {error && <div role="alert" className="rounded-xl border border-rose-200 bg-rose-50 p-3 text-sm font-bold text-rose-700">{error}<Button variant="secondary" className="ml-3" onClick={load}><RotateCcw size={15}/> Retry</Button></div>}
    {loading ? <div className="rounded-2xl border border-slate-200 bg-white p-6 text-sm font-bold text-slate-500">Loading external gates...</div> : data.total === 0 ? <>
      <EmptyState icon={<ShieldCheck size={20}/>} title="No project gates generated" description="Generate the project-owned gate snapshot after project tasks exist."/>
      {canGenerate && <section className="rounded-2xl border border-blue-200 bg-blue-50/60 p-4 sm:p-5"><label className="flex items-start gap-3 rounded-xl border border-blue-200 bg-white p-3 text-sm text-slate-700"><input type="checkbox" checked={confirmed} disabled={busy} onChange={event => setConfirmed(event.target.checked)} className="mt-0.5 size-4"/><span>I confirm the selected published template is correct. Gates will remain pending review and the project will remain Draft.</span></label><Button className="mt-4 w-full sm:w-auto" disabled={!confirmed || busy} loading={busy} onClick={generate}>Generate gates</Button></section>}
    </> : <>
      {canDecide && <section className="flex flex-wrap items-center gap-3 rounded-2xl border border-slate-200 bg-slate-50 p-3 sm:p-4">
        <label className="flex items-center gap-2 text-sm font-bold text-slate-700"><input type="checkbox" className="size-4" checked={selected.size > 0 && selected.size === data.items.length} onChange={toggleSelectAll}/>Select all</label>
        <span className="text-xs font-bold text-slate-500">{selected.size} selected</span>
        <div className="ml-auto flex flex-wrap items-center gap-2">
          <Button size="sm" variant="secondary" disabled={selected.size === 0 || bulkBusy} loading={bulkBusy && !bulkNotApplicable} onClick={() => applyBulkDecision("applicable")}><Check size={14}/> Mark selected Applicable</Button>
          <Button size="sm" variant="danger" disabled={selected.size === 0 || bulkBusy} onClick={() => setBulkNotApplicable(true)}><X size={14}/> Mark selected Not Applicable</Button>
        </div>
        {bulkError && <div role="alert" className="w-full rounded-xl border border-rose-200 bg-rose-50 p-3 text-sm font-bold text-rose-700">{bulkError}</div>}
      </section>}
      <div className="grid gap-3">{data.items.map(gate => <article key={gate.id} className="rounded-2xl border border-slate-200 bg-white p-4 sm:p-5"><div className="flex flex-wrap items-start justify-between gap-3"><div className="flex min-w-0 items-start gap-3">{canDecide && <input type="checkbox" className="mt-1 size-4 shrink-0" checked={selected.has(gate.id)} onChange={() => toggleSelected(gate.id)} aria-label={`Select ${gate.code}`}/>}<div className="min-w-0"><div className="flex flex-wrap items-center gap-2"><span className="text-xs font-black text-blue-700">{gate.code}</span><Pill tone="orange">{gate.status.replaceAll("_", " ")}</Pill><Pill tone={gate.applicability_state === "applicable" ? "green" : gate.applicability_state === "not_applicable" ? "red" : "orange"}>{(gate.applicability_state || "pending_review").replaceAll("_", " ")}</Pill><Pill tone="gray">{mappingLabel[gate.mapping_classification]}</Pill></div><h4 className="mt-2 font-black text-slate-950">{gate.approval_name}</h4>{gate.description && <p className="mt-1 text-sm leading-6 text-slate-600">{gate.description}</p>}</div></div><span className="text-xs font-bold text-slate-400">#{gate.sequence}</span></div><div className="mt-4 grid gap-2 text-xs sm:grid-cols-3"><div className="rounded-xl bg-slate-50 p-3"><span className="block font-black uppercase tracking-wide text-slate-400">Source</span><strong className="mt-1 block text-slate-700">{gate.source === "project_manual" ? "Manual" : "Template"}</strong></div><div className="rounded-xl bg-slate-50 p-3"><span className="block font-black uppercase tracking-wide text-slate-400">PM owner</span><strong className="mt-1 block text-slate-700">{gate.accountable_pm_name}</strong></div><div className="rounded-xl bg-slate-50 p-3"><span className="block font-black uppercase tracking-wide text-slate-400">Mapping</span><strong className="mt-1 block text-slate-700">{gate.mapping_classification === "exact" ? `${gate.exact_task_count} task links` : gate.broad_mapping_text || "Configuration required"}</strong>{gate.blocking && <small className="mt-1 block font-bold text-rose-600">Blocking</small>}</div></div><div className="mt-4 border-t border-slate-100 pt-4"><GateApplicabilityControls projectId={project.id} gate={gate} canDecide={canDecide} onDecided={load}/></div></article>)}</div>
    </>}
    {showManual && <ProjectManualGateModal projectId={project.id} onClose={() => setShowManual(false)} onCreated={load}/>}
    {bulkNotApplicable && <Modal title="Mark selected gates Not Applicable" subtitle={`${selected.size} gate${selected.size === 1 ? "" : "s"} selected`} onClose={() => { if (!bulkBusy) { setBulkNotApplicable(false); setBulkReason(""); } }} className="sm:max-w-xl">
      <div className="grid gap-5">
        <div className="rounded-2xl border border-rose-200 bg-rose-50 p-4"><p className="text-sm font-black text-rose-950">Each selected gate will be retained but excluded from the project requirement set.</p><p className="mt-1 text-xs leading-5 text-slate-600">The same reason is recorded against every selected gate, append-only in each gate's own history.</p></div>
        <Field label="Reason (required)" htmlFor="bulk-gate-decision-reason">
          <Textarea id="bulk-gate-decision-reason" value={bulkReason} onChange={event => setBulkReason(event.target.value)} maxLength={2000} placeholder="Explain why these gates do not apply"/>
        </Field>
        {bulkError && <div role="alert" className="rounded-xl border border-rose-200 bg-rose-50 px-4 py-3 text-sm font-bold text-rose-700">{bulkError}</div>}
        <div className="grid gap-2 sm:grid-cols-2">
          <Button variant="secondary" disabled={bulkBusy} onClick={() => { setBulkNotApplicable(false); setBulkReason(""); }}>Cancel</Button>
          <Button variant="danger" loading={bulkBusy} disabled={!bulkReason.trim()} onClick={() => applyBulkDecision("not_applicable", bulkReason.trim())}>Confirm Not Applicable</Button>
        </div>
      </div>
    </Modal>}
    {data.total > 0 && <div className="rounded-xl border border-emerald-200 bg-emerald-50 p-3 text-sm font-bold text-emerald-800"><Check className="mr-2 inline" size={16}/>{data.total} gates generated. Retry is idempotent and creates no duplicates.</div>}
  </div>;
}
