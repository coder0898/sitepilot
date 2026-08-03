import { useState } from "react";
import { taskExecutionApi } from "../../../api/taskExecutionApi";
import { Button, Field, Input, Pill, Select, Textarea } from "../../../components/ui";

const DELAY_RESPONSIBILITY_OPTIONS = [
  ["vendor", "Vendor"], ["client", "Client"], ["approval", "Approval"],
  ["design", "Design"], ["site_readiness", "Site readiness"], ["internal", "Internal"], ["other", "Other"],
];

function BlockerRow({ projectId, task, blocker, onChanged }) {
  const [resolving, setResolving] = useState(false);
  const [error, setError] = useState("");

  async function resolve() {
    setResolving(true);
    setError("");
    try {
      await taskExecutionApi.resolveBlocker(projectId, task.id, blocker.id);
      await onChanged();
    } catch (caught) {
      setError(caught?.message || "This blocker could not be resolved.");
    } finally {
      setResolving(false);
    }
  }

  return <div className="rounded-lg border border-amber-200 bg-white p-3 text-sm">
    <div className="flex flex-wrap items-center justify-between gap-2">
      <strong className="capitalize text-amber-900">{blocker.type}</strong>
      <div className="flex items-center gap-2">
        <Pill tone={blocker.resolved_at ? "green" : "orange"}>{blocker.resolved_at ? "Resolved" : "Open"}</Pill>
        {!blocker.resolved_at && <Button size="sm" variant="secondary" loading={resolving} onClick={resolve}>Resolve</Button>}
      </div>
    </div>
    <p className="mt-1 text-slate-600">{blocker.description}</p>
    {error && <p className="mt-1 text-xs font-bold text-rose-700">{error}</p>}
  </div>;
}

// U5: blocker and delay capture (BR-010). Always visible regardless of
// lifecycle_status - blocked/delayed conditions are independent of and
// combinable with task status, per the plan's Approach.
export function TaskBlockerDelayPanel({ projectId, task, onChanged }) {
  const [blockerType, setBlockerType] = useState("");
  const [blockerDescription, setBlockerDescription] = useState("");
  const [blockerSubmitting, setBlockerSubmitting] = useState(false);
  const [blockerError, setBlockerError] = useState("");

  const [responsibilityType, setResponsibilityType] = useState("vendor");
  const [vendorId, setVendorId] = useState("");
  const [delayReason, setDelayReason] = useState("");
  const [impactDays, setImpactDays] = useState("1");
  const [delaySubmitting, setDelaySubmitting] = useState(false);
  const [delayError, setDelayError] = useState("");

  async function submitBlocker(event) {
    event.preventDefault();
    setBlockerSubmitting(true);
    setBlockerError("");
    try {
      await taskExecutionApi.logBlocker(projectId, task.id, { type: blockerType.trim(), description: blockerDescription.trim() });
      setBlockerType("");
      setBlockerDescription("");
      await onChanged();
    } catch (caught) {
      setBlockerError(caught?.message || "This blocker could not be logged.");
    } finally {
      setBlockerSubmitting(false);
    }
  }

  async function submitDelay(event) {
    event.preventDefault();
    setDelaySubmitting(true);
    setDelayError("");
    try {
      await taskExecutionApi.logDelay(projectId, task.id, {
        responsibility_type: responsibilityType,
        responsible_vendor_id: responsibilityType === "vendor" ? vendorId.trim() : null,
        reason: delayReason.trim(),
        impact_days: Number(impactDays),
      });
      setVendorId("");
      setDelayReason("");
      setImpactDays("1");
      await onChanged();
    } catch (caught) {
      setDelayError(caught?.message || "This delay could not be logged.");
    } finally {
      setDelaySubmitting(false);
    }
  }

  return <div className="grid gap-4">
    <section className="rounded-xl border border-amber-200 bg-amber-50 p-4">
      <h4 className="text-xs font-black uppercase tracking-wide text-amber-700">Blockers</h4>
      <div className="mt-2 grid gap-2">
        {task.blockers.map(blocker => <BlockerRow key={blocker.id} projectId={projectId} task={task} blocker={blocker} onChanged={onChanged}/>)}
        {!task.blockers.length && <p className="text-sm text-amber-800">No blockers logged.</p>}
      </div>
      <form className="mt-3 grid gap-2 border-t border-amber-200 pt-3 sm:grid-cols-[160px_1fr_auto] sm:items-end" onSubmit={submitBlocker}>
        <Field label="Type"><Input value={blockerType} onChange={event => setBlockerType(event.target.value)} placeholder="e.g. material" required/></Field>
        <Field label="Description"><Input value={blockerDescription} onChange={event => setBlockerDescription(event.target.value)} placeholder="Describe the blocker" required/></Field>
        <Button type="submit" size="sm" loading={blockerSubmitting} disabled={!blockerType.trim() || !blockerDescription.trim()}>Log blocker</Button>
      </form>
      {blockerError && <p className="mt-2 text-xs font-bold text-rose-700">{blockerError}</p>}
    </section>

    <section className="rounded-xl border border-slate-200 bg-white p-4">
      <h4 className="text-xs font-black uppercase tracking-wide text-slate-500">Delays</h4>
      <div className="mt-2 grid gap-2">
        {task.delays.map(delay => <div key={delay.id} className="rounded-lg border border-slate-100 bg-slate-50 p-3 text-sm"><div className="flex flex-wrap items-center justify-between gap-2"><strong className="capitalize text-slate-800">{delay.responsibility_type.replaceAll("_", " ")}</strong><span className="text-xs font-bold text-slate-500">{delay.impact_days} day{delay.impact_days === 1 ? "" : "s"}</span></div><p className="mt-1 text-slate-600">{delay.reason}</p></div>)}
        {!task.delays.length && <p className="text-sm text-slate-500">No delays logged.</p>}
      </div>
      <form className="mt-3 grid gap-2 border-t border-slate-100 pt-3 sm:grid-cols-2" onSubmit={submitDelay}>
        <Field label="Responsibility"><Select value={responsibilityType} onChange={event => setResponsibilityType(event.target.value)}>{DELAY_RESPONSIBILITY_OPTIONS.map(([value, label]) => <option key={value} value={value}>{label}</option>)}</Select></Field>
        <Field label="Impact (days)"><Input type="number" min="1" value={impactDays} onChange={event => setImpactDays(event.target.value)} required/></Field>
        {responsibilityType === "vendor" && <Field label="Vendor ID" className="sm:col-span-2" hint="Vendor picker arrives with Phase 2's vendor integration; enter the vendor's ID for now."><Input value={vendorId} onChange={event => setVendorId(event.target.value)} required/></Field>}
        <Field label="Reason" className="sm:col-span-2"><Textarea value={delayReason} onChange={event => setDelayReason(event.target.value)} placeholder="What is causing the delay?" required/></Field>
        <Button type="submit" size="sm" className="sm:col-span-2" loading={delaySubmitting} disabled={!delayReason.trim() || (responsibilityType === "vendor" && !vendorId.trim())}>Log delay</Button>
      </form>
      {delayError && <p className="mt-2 text-xs font-bold text-rose-700">{delayError}</p>}
    </section>
  </div>;
}
