import { AlertTriangle, Clock3, X } from "lucide-react";
import { useEffect, useState } from "react";
import { taskExecutionApi } from "../../../api/taskExecutionApi";
import { Button, Field, Input, Pill, Select, Textarea } from "../../../components/ui";

const DELAY_RESPONSIBILITY_OPTIONS = [
  ["vendor", "Vendor"], ["client", "Client"], ["approval", "Approval"],
  ["design", "Design"], ["site_readiness", "Site readiness"], ["internal", "Internal"], ["other", "Other"],
];

// The backend column is a plain uuid.UUID (no vendor picker exists yet - see
// the plan's Key Technical Decisions), so free text like a vendor code would
// always 422. Validate the format client-side to fail fast with a clear
// message instead of a confusing backend error.
const UUID_PATTERN = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

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

  return <div className="rounded-lg border border-slate-100 bg-slate-50 px-3 py-2 text-sm">
    <div className="flex flex-wrap items-center justify-between gap-2">
      <span className="flex items-center gap-2"><strong className="capitalize text-slate-800">{blocker.type}</strong><Pill tone={blocker.resolved_at ? "green" : "orange"}>{blocker.resolved_at ? "Resolved" : "Open"}</Pill></span>
      {!blocker.resolved_at && <Button size="sm" variant="secondary" loading={resolving} onClick={resolve}>Resolve</Button>}
    </div>
    <p className="mt-0.5 text-slate-600">{blocker.description}</p>
    {error && <p className="mt-1 text-xs font-bold text-rose-700">{error}</p>}
  </div>;
}

function BlockerForm({ projectId, task, onDone, onChanged }) {
  const [type, setType] = useState("");
  const [description, setDescription] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState("");

  async function submit(event) {
    event.preventDefault();
    setSubmitting(true);
    setError("");
    try {
      await taskExecutionApi.logBlocker(projectId, task.id, { type: type.trim(), description: description.trim() });
      await onChanged();
      onDone();
    } catch (caught) {
      setError(caught?.message || "This blocker could not be logged.");
    } finally {
      setSubmitting(false);
    }
  }

  return <form className="mt-2 grid gap-2 rounded-lg border border-amber-200 bg-amber-50/60 p-3 sm:grid-cols-[160px_1fr_auto]" onSubmit={submit}>
    <Field label="Type"><Input value={type} onChange={event => setType(event.target.value)} placeholder="e.g. material" required/></Field>
    <Field label="Description"><Input value={description} onChange={event => setDescription(event.target.value)} placeholder="Describe the blocker" required/></Field>
    <div className="flex items-end gap-2">
      <Button type="submit" size="sm" loading={submitting} disabled={!type.trim() || !description.trim()}>Log blocker</Button>
      <Button type="button" size="sm" variant="ghost" disabled={submitting} onClick={onDone}>Cancel</Button>
    </div>
    {error && <p className="text-xs font-bold text-rose-700 sm:col-span-3">{error}</p>}
  </form>;
}

function DelayForm({ projectId, task, onDone, onChanged }) {
  const [responsibilityType, setResponsibilityType] = useState("vendor");
  const [vendorId, setVendorId] = useState("");
  const [reason, setReason] = useState("");
  const [impactDays, setImpactDays] = useState("1");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState("");

  const vendorIdInvalid = responsibilityType === "vendor" && vendorId.trim() && !UUID_PATTERN.test(vendorId.trim());

  async function submit(event) {
    event.preventDefault();
    if (responsibilityType === "vendor" && !UUID_PATTERN.test(vendorId.trim())) {
      setError("Vendor ID must be a valid UUID (the vendor's V2 record id, not a vendor code).");
      return;
    }
    setSubmitting(true);
    setError("");
    try {
      await taskExecutionApi.logDelay(projectId, task.id, {
        responsibility_type: responsibilityType,
        responsible_vendor_id: responsibilityType === "vendor" ? vendorId.trim() : null,
        reason: reason.trim(),
        impact_days: Number(impactDays),
      });
      await onChanged();
      onDone();
    } catch (caught) {
      setError(caught?.message || "This delay could not be logged.");
    } finally {
      setSubmitting(false);
    }
  }

  return <form className="mt-2 grid gap-2 rounded-lg border border-slate-200 bg-slate-50/60 p-3 sm:grid-cols-2" onSubmit={submit}>
    <Field label="Responsibility"><Select value={responsibilityType} onChange={event => setResponsibilityType(event.target.value)}>{DELAY_RESPONSIBILITY_OPTIONS.map(([value, label]) => <option key={value} value={value}>{label}</option>)}</Select></Field>
    <Field label="Impact (days)"><Input type="number" min="1" value={impactDays} onChange={event => setImpactDays(event.target.value)} required/></Field>
    {responsibilityType === "vendor" && <Field label="Vendor ID" className="sm:col-span-2" error={vendorIdInvalid ? "Must be a valid UUID." : null} hint={vendorIdInvalid ? null : "Vendor picker arrives with Phase 2's vendor integration; enter the vendor's V2 record UUID for now."}><Input value={vendorId} onChange={event => setVendorId(event.target.value)} placeholder="e.g. 3fa85f64-5717-4562-b3fc-2c963f66afa6" required/></Field>}
    <Field label="Reason" className="sm:col-span-2"><Textarea value={reason} onChange={event => setReason(event.target.value)} placeholder="What is causing the delay?" required/></Field>
    <div className="flex gap-2 sm:col-span-2">
      <Button type="submit" size="sm" loading={submitting} disabled={!reason.trim() || (responsibilityType === "vendor" && (!vendorId.trim() || vendorIdInvalid))}>Log delay</Button>
      <Button type="button" size="sm" variant="ghost" disabled={submitting} onClick={onDone}>Cancel</Button>
    </div>
    {error && <p className="text-xs font-bold text-rose-700 sm:col-span-2">{error}</p>}
  </form>;
}

// U5: blocker and delay capture (BR-010). Independent of and combinable
// with lifecycle_status - logging either never changes task status. Both
// forms are collapsed by default behind compact "Report..." actions
// (progressive disclosure); only the selected form opens, and cancelling
// it never touches the task's status.
//
// `autoOpen` ("blocker" | "delay" | undefined): a quick-action button
// elsewhere on the page can drive this open remotely (e.g. TaskDetailDrawer's
// "Report Delay - Blocker" action) instead of the user finding and clicking
// the toggle themselves. Re-applied whenever it changes, not just on mount,
// so a second quick-action click while this panel is already open still
// switches to the requested form.
export function TaskBlockerDelayPanel({ projectId, task, onChanged, autoOpen }) {
  const [openForm, setOpenForm] = useState(autoOpen || null); // "blocker" | "delay" | null
  useEffect(() => { if (autoOpen) setOpenForm(autoOpen); }, [autoOpen]);
  const openBlockers = task.blockers.filter(b => !b.resolved_at).length;

  return <section className="rounded-xl border border-slate-200 bg-white p-4">
    <div className="flex flex-wrap items-center justify-between gap-2">
      <h4 className="text-xs font-black uppercase tracking-wide text-slate-500">Blockers &amp; delays</h4>
      <div className="flex flex-wrap gap-2">
        <Button size="sm" variant={openForm === "blocker" ? "primary" : "secondary"} onClick={() => setOpenForm(openForm === "blocker" ? null : "blocker")}>
          {openForm === "blocker" ? <X size={13}/> : <AlertTriangle size={13}/>} Report blocker
        </Button>
        <Button size="sm" variant={openForm === "delay" ? "primary" : "secondary"} onClick={() => setOpenForm(openForm === "delay" ? null : "delay")}>
          {openForm === "delay" ? <X size={13}/> : <Clock3 size={13}/>} Report delay
        </Button>
      </div>
    </div>

    <div className="mt-2 flex flex-wrap items-center gap-3 text-xs font-bold text-slate-500">
      <span>{openBlockers > 0 ? <span className="text-amber-700">{openBlockers} open blocker{openBlockers === 1 ? "" : "s"}</span> : "No open blockers"}</span>
      <span aria-hidden="true">&middot;</span>
      <span>{task.delays.length > 0 ? `${task.delays.length} delay${task.delays.length === 1 ? "" : "s"} logged` : "No delays logged"}</span>
    </div>

    {task.blockers.length > 0 && <div className="mt-2 grid gap-1.5">{task.blockers.map(blocker => <BlockerRow key={blocker.id} projectId={projectId} task={task} blocker={blocker} onChanged={onChanged}/>)}</div>}
    {openForm === "blocker" && <BlockerForm projectId={projectId} task={task} onChanged={onChanged} onDone={() => setOpenForm(null)}/>}

    {task.delays.length > 0 && <div className="mt-2 grid gap-1.5">{task.delays.map(delay => <div key={delay.id} className="rounded-lg border border-slate-100 bg-slate-50 px-3 py-2 text-sm"><div className="flex flex-wrap items-center justify-between gap-2"><strong className="capitalize text-slate-800">{delay.responsibility_type.replaceAll("_", " ")}</strong><span className="text-xs font-bold text-slate-500">{delay.impact_days} day{delay.impact_days === 1 ? "" : "s"}</span></div><p className="mt-0.5 text-slate-600">{delay.reason}</p></div>)}</div>}
    {openForm === "delay" && <DelayForm projectId={projectId} task={task} onChanged={onChanged} onDone={() => setOpenForm(null)}/>}
  </section>;
}
