import { Truck, UserMinus } from "lucide-react";
import { useEffect, useState } from "react";
import { vendorAssignmentApi } from "../../../api/vendorAssignmentApi";
import { Button, Field, Pill, Select, Textarea } from "../../../components/ui";
import { VendorAcknowledgementForm } from "./VendorAcknowledgementForm";

const STATUS_TONE = { pending_ack: "orange", acknowledged: "green", declined: "red" };

// Unassign a vendor from this one task (soft removal - ends_at on the
// TaskVendorAssignment). The vendor stays mapped to the project.
function UnassignVendorControl({ projectId, task, assignment, onChanged }) {
  const [confirming, setConfirming] = useState(false);
  const [reason, setReason] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState("");

  async function unassign() {
    setSubmitting(true);
    setError("");
    try {
      await vendorAssignmentApi.unassignTask(projectId, task.id, assignment.id, { reason: reason.trim() });
      setConfirming(false);
      setReason("");
      await onChanged();
    } catch (caught) {
      setError(caught?.message || "This vendor could not be unassigned from the task.");
    } finally {
      setSubmitting(false);
    }
  }

  if (!confirming) {
    return <button type="button" className="inline-flex items-center gap-1 text-xs font-bold text-rose-700 hover:underline" onClick={() => setConfirming(true)}><UserMinus size={12}/> Unassign</button>;
  }

  return <div className="mt-2 rounded-lg border border-rose-200 bg-rose-50/60 p-2">
    <Textarea className="min-h-14" value={reason} onChange={event => setReason(event.target.value)} placeholder="Reason for unassigning (required)"/>
    {error && <p className="mt-1 text-xs font-bold text-rose-700">{error}</p>}
    <div className="mt-2 flex gap-2">
      <Button size="sm" variant="danger" loading={submitting} disabled={reason.trim().length < 4} onClick={unassign}>Confirm</Button>
      <Button size="sm" variant="secondary" disabled={submitting} onClick={() => { setConfirming(false); setReason(""); setError(""); }}>Cancel</Button>
    </div>
  </div>;
}

// U2/U3: delegate a mapped vendor to this task (R3), then track its
// acknowledgement/activity history alongside it. Delegation never touches
// Task.lifecycle_status or Phase 1's accountable-Supervisor derivation - a
// vendor assignment is purely additive information for this task.
export function TaskVendorDelegationForm({ projectId, task, user, onChanged }) {
  const [mappedVendors, setMappedVendors] = useState([]);
  const [assignments, setAssignments] = useState([]);
  const [loading, setLoading] = useState(true);
  const [vendorId, setVendorId] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState("");
  const canManage = ["admin", "super_admin", "project_manager"].includes(user?.role);

  async function load() {
    setLoading(true);
    setError("");
    try {
      const [vendors, taskAssignments] = await Promise.all([
        vendorAssignmentApi.listProjectVendors(projectId),
        vendorAssignmentApi.listTaskVendorAssignments(projectId, task.id),
      ]);
      setMappedVendors(vendors);
      setAssignments(taskAssignments);
    } catch (caught) {
      setError(caught?.message || "This task's vendor delegation could not be loaded.");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => { load(); }, [projectId, task.id]);

  async function refresh() {
    await load();
    await onChanged();
  }

  // A vendor with a live (pending_ack/acknowledged, not yet ended) assignment
  // on this task isn't offered again - re-delegation only makes sense after
  // a decline or an unassignment.
  const liveVendorIds = new Set(assignments.filter(a => a.status !== "declined" && !a.ends_at).map(a => a.vendor_id));
  const candidates = mappedVendors.filter(v => !liveVendorIds.has(v.vendor_id));

  async function delegate(event) {
    event.preventDefault();
    setSubmitting(true);
    setError("");
    try {
      await vendorAssignmentApi.delegateTask(projectId, task.id, { vendor_id: vendorId });
      setVendorId("");
      await refresh();
    } catch (caught) {
      setError(caught?.message || "This vendor could not be delegated to the task.");
    } finally {
      setSubmitting(false);
    }
  }

  if (loading) return <div className="rounded-xl border border-slate-200 bg-white p-4 text-sm text-slate-500">Loading vendor delegation...</div>;

  return <section className="rounded-xl border border-slate-200 bg-white p-4">
    <h4 className="flex items-center gap-2 text-xs font-black uppercase tracking-wide text-slate-500"><Truck size={14}/> Vendor delegation</h4>

    {error && <p className="mt-2 text-xs font-bold text-rose-700">{error}</p>}

    {assignments.length === 0 ? <p className="mt-2 text-sm text-slate-500">No vendor delegated to this task.</p> : <div className="mt-3 grid gap-3">{assignments.map(assignment => <article key={assignment.id} className={`rounded-lg border border-slate-100 bg-slate-50 p-3 ${assignment.ends_at ? "opacity-70" : ""}`}>
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="flex items-center gap-2"><strong className="text-sm text-slate-900">{assignment.vendor_name}</strong><Pill tone={assignment.ends_at ? "gray" : (STATUS_TONE[assignment.status] || "gray")}>{assignment.ends_at ? "unassigned" : assignment.status.replaceAll("_", " ")}</Pill></div>
        {canManage && !assignment.ends_at && <UnassignVendorControl projectId={projectId} task={task} assignment={assignment} onChanged={refresh}/>}
      </div>
      {assignment.ends_at && <p className="mt-1 text-xs text-slate-400">Unassigned {new Date(assignment.ends_at).toLocaleDateString("en-GB")}</p>}
      <VendorAcknowledgementForm projectId={projectId} task={task} assignment={assignment} canManage={canManage} onChanged={refresh}/>
    </article>)}</div>}

    {canManage && <form className="mt-3 grid gap-2 border-t border-slate-100 pt-3 sm:grid-cols-[1fr_auto]" onSubmit={delegate}>
      <Field label="Delegate a mapped vendor">
        <Select value={vendorId} onChange={event => setVendorId(event.target.value)} required>
          <option value="">{candidates.length ? "Select vendor" : "No mapped vendors available"}</option>
          {candidates.map(candidate => <option key={candidate.vendor_id} value={candidate.vendor_id}>{candidate.vendor_name}</option>)}
        </Select>
      </Field>
      <div className="flex items-end"><Button type="submit" size="sm" loading={submitting} disabled={!vendorId}>Delegate</Button></div>
    </form>}
  </section>;
}
