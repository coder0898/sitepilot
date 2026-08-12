import { useState } from "react";
import { taskExecutionApi } from "../../../api/taskExecutionApi";
import { Button, Field, Pill, Select, Textarea } from "../../../components/ui";

// U8: record an external approval's outcome without leaving the tab.
//
// Every role predicate here is UX only - it decides what to offer, never
// what is allowed. `ProjectGateStatusService._require_recorder` is the
// authority, and it is checked per transition, not per actor.

const STATUS_TONE = {
  approved: "green",
  not_required: "gray",
  rejected: "red",
  submitted: "blue",
  pending_review: "orange",
};

// Mirrors GATE_STATUS_TRANSITIONS in backend/app/execution_models.py.
const NEXT_STATUSES = {
  pending_review: [["submitted", "Mark submitted"], ["not_required", "Mark not required"]],
  submitted: [["approved", "Record approval"], ["rejected", "Record rejection"]],
  rejected: [["submitted", "Record resubmission"]],
  approved: [["submitted", "Reopen as submitted"]],
  not_required: [["pending_review", "Return to review"]],
};

// Mirrors GATE_DELEGABLE_TRANSITIONS in backend/app/execution_models.py.
//
// External approvals are Admin's responsibility, so every consequential move
// is Admin's. The only exceptions are the two that state a fact about the
// delegate's own work - "I lodged it" - rather than what an external
// authority decided.
const DELEGABLE = new Set(["pending_review>submitted", "rejected>submitted"]);

export function canRecordGateOutcome(user, gate, from, to) {
  if (user.role === "super_admin" || user.role === "admin") return true;
  if (!DELEGABLE.has(`${from}>${to}`)) return false;
  return (gate.active_delegate_user_ids || []).includes(user.id);
}

export function ExecutionGateStatusControl({ projectId, gate, user, onRecorded }) {
  const [target, setTarget] = useState("");
  const [reason, setReason] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState("");

  const options = (NEXT_STATUSES[gate.status] || []).filter(([to]) => canRecordGateOutcome(user, gate, gate.status, to));
  if (!options.length) return null;

  async function submit(event) {
    event.preventDefault();
    setSubmitting(true);
    setError("");
    try {
      await taskExecutionApi.recordGateStatus(projectId, gate.id, { status: target, reason: reason.trim() });
      setTarget("");
      setReason("");
      await onRecorded();
    } catch (caught) {
      // The server guard is authoritative; surface exactly what it said.
      setError(caught?.message || "This outcome could not be recorded.");
    } finally {
      setSubmitting(false);
    }
  }

  return <form className="mt-3 grid gap-2 rounded-xl border border-slate-200 bg-slate-50/60 p-3 sm:grid-cols-2" onSubmit={submit}>
    <Field label="Record outcome">
      <Select value={target} onChange={event => setTarget(event.target.value)}>
        <option value="">Select an outcome</option>
        {options.map(([value, label]) => <option key={value} value={value}>{label}</option>)}
      </Select>
    </Field>
    <Field label="Reason" className="sm:col-span-2">
      <Textarea value={reason} onChange={event => setReason(event.target.value)} placeholder="What happened, and who said so?" required/>
    </Field>
    <div className="sm:col-span-2">
      <Button type="submit" size="sm" loading={submitting} disabled={!target || !reason.trim()}>Record</Button>
      {error && <p className="mt-2 text-sm font-bold text-rose-700">{error}</p>}
    </div>
  </form>;
}

export function ExecutionGateStatusPill({ status }) {
  return <Pill tone={STATUS_TONE[status] || "gray"}>{String(status || "pending_review").replaceAll("_", " ")}</Pill>;
}
