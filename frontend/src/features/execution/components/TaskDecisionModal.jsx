import { Hourglass } from "lucide-react";
import { useState } from "react";
import { taskExecutionApi } from "../../../api/taskExecutionApi";
import { Button, Field, Modal, Textarea } from "../../../components/ui";

const AWAITING_MESSAGE = {
  verify: "Awaiting Supervisor verification",
  approve: "Awaiting PM approval",
};

// task_kind is nullable - a task whose template row never had a kind
// assigned during authoring still needs a real completion path, so it's
// treated as ordinary `work` here, matching TaskVerificationService.verify
// and build_approval_metadata's `is_work_task_kind` normalization. Only an
// explicit "approval_gate" (or "milestone", which never reaches this modal
// since milestones auto-complete) opts a task out of the work path.
function isWorkTaskKind(taskKind) {
  return taskKind !== "milestone" && taskKind !== "approval_gate";
}

// U4: Supervisor verification / PM approval decisions (BR-008). Mirrors
// TaskApplicabilityDecisionModal.jsx's shape - buttons plus a conditional
// modal, a required reason only on reject, and an onDecided?.() callback
// that refreshes the board row rather than the whole page.
function resolveAction(task) {
  if (isWorkTaskKind(task.task_kind) && task.lifecycle_status === "submitted") return "verify";
  if (task.task_kind === "approval_gate" && task.lifecycle_status === "submitted") return "approve";
  if (isWorkTaskKind(task.task_kind) && task.task_class === "class_a" && task.lifecycle_status === "verified") return "approve";
  return null;
}

// Mirrors the backend's actual authority (task_verification.py
// `_require_verifier`, task_approval.py `_require_approver`): the
// Supervisor may verify (or stand in as an audited PM fallback), but only
// the PM (or Admin/Super Admin) may record a PM approval decision - a
// Supervisor must never see an Approve action it cannot actually use.
function actorCanAct(action, role) {
  if (!role) return false;
  if (role === "admin" || role === "super_admin") return true;
  if (action === "verify") return role === "supervisor" || role === "project_manager";
  if (action === "approve") return role === "project_manager";
  return false;
}

export function TaskDecisionModal({ projectId, task, user, onDecided }) {
  const action = resolveAction(task);
  const [decision, setDecision] = useState(null); // "positive" | "rejected"
  const [remarks, setRemarks] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState("");

  if (!action) return null;

  if (!actorCanAct(action, user?.role)) {
    return <div className="flex items-center gap-2 rounded-xl border border-slate-200 bg-slate-50 px-4 py-3 text-sm font-bold text-slate-500">
      <Hourglass size={15}/> {AWAITING_MESSAGE[action]}
    </div>;
  }

  const positiveDecision = action === "verify" ? "verified" : "approved";
  const positiveLabel = action === "verify" ? "Verify completion" : "Approve";
  const modalTitle = action === "verify" ? "Verify task completion" : "Approve task";
  const confirmLabel = action === "verify" ? "Confirm verification" : "Confirm approval";

  function open(next) {
    setError("");
    setRemarks("");
    setDecision(next);
  }

  async function submit(event) {
    event.preventDefault();
    const cleanRemarks = remarks.trim();
    if (decision === "rejected" && !cleanRemarks) {
      setError("A correction reason is required to reject this task.");
      return;
    }
    setSubmitting(true);
    setError("");
    try {
      const call = action === "verify" ? taskExecutionApi.verify : taskExecutionApi.approve;
      await call(projectId, task.id, {
        decision: decision === "rejected" ? "rejected" : positiveDecision,
        remarks: cleanRemarks || null,
      });
      setDecision(null);
      await onDecided();
    } catch (caught) {
      setError(caught?.message || "This decision could not be recorded.");
    } finally {
      setSubmitting(false);
    }
  }

  return <>
    <section className="rounded-xl border border-violet-200 bg-violet-50 p-4">
      <h4 className="text-xs font-black uppercase tracking-wide text-violet-800">{action === "verify" ? "Supervisor verification" : "PM approval"}</h4>
      <div className="mt-3 flex flex-wrap gap-2">
        <Button size="sm" onClick={() => open("positive")}>{positiveLabel}</Button>
        <Button size="sm" variant="danger" onClick={() => open("rejected")}>Reject</Button>
      </div>
    </section>

    {decision && <Modal title={decision === "rejected" ? "Reject and reopen task" : modalTitle} subtitle={`${task.original_code} - ${task.title}`} onClose={() => { if (!submitting) setDecision(null); }} className="sm:max-w-xl">
      <form className="grid gap-4" onSubmit={submit}>
        <Field label={decision === "rejected" ? "Correction reason (required)" : "Remarks (optional)"}>
          <Textarea value={remarks} onChange={event => setRemarks(event.target.value)} required={decision === "rejected"} placeholder={decision === "rejected" ? "Explain what needs correcting before resubmission" : "Optional remarks"}/>
        </Field>
        {error && <div role="alert" className="rounded-xl border border-rose-200 bg-rose-50 px-4 py-3 text-sm font-bold text-rose-700">{error}</div>}
        <div className="grid gap-2 sm:grid-cols-2">
          <Button type="button" variant="secondary" disabled={submitting} onClick={() => setDecision(null)}>Cancel</Button>
          <Button type="submit" variant={decision === "rejected" ? "danger" : "primary"} loading={submitting}>{decision === "rejected" ? "Confirm rejection" : confirmLabel}</Button>
        </div>
      </form>
    </Modal>}
  </>;
}
