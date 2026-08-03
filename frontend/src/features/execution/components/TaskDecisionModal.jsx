import { useState } from "react";
import { taskExecutionApi } from "../../../api/taskExecutionApi";
import { Button, Field, Modal, Textarea } from "../../../components/ui";

// U4: Supervisor verification / PM approval decisions (BR-008). Mirrors
// TaskApplicabilityDecisionModal.jsx's shape - buttons plus a conditional
// modal, a required reason only on reject, and an onDecided?.() callback
// that refreshes the board row rather than the whole page.
function resolveAction(task) {
  if (task.task_kind === "work" && task.lifecycle_status === "submitted") return "verify";
  if (task.task_kind === "approval_gate" && task.lifecycle_status === "submitted") return "approve";
  if (task.task_kind === "work" && task.task_class === "class_a" && task.lifecycle_status === "verified") return "approve";
  return null;
}

export function TaskDecisionModal({ projectId, task, onDecided }) {
  const action = resolveAction(task);
  const [decision, setDecision] = useState(null); // "positive" | "rejected"
  const [remarks, setRemarks] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState("");

  if (!action) return null;

  const positiveDecision = action === "verify" ? "verified" : "approved";
  const positiveLabel = action === "verify" ? "Verify" : "Approve";

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

    {decision && <Modal title={decision === "rejected" ? "Reject and reopen task" : `${positiveLabel} task`} subtitle={`${task.original_code} - ${task.title}`} onClose={() => { if (!submitting) setDecision(null); }} className="sm:max-w-xl">
      <form className="grid gap-4" onSubmit={submit}>
        <Field label={decision === "rejected" ? "Correction reason (required)" : "Remarks (optional)"}>
          <Textarea value={remarks} onChange={event => setRemarks(event.target.value)} required={decision === "rejected"} placeholder={decision === "rejected" ? "Explain what needs correcting before resubmission" : "Optional remarks"}/>
        </Field>
        {error && <div role="alert" className="rounded-xl border border-rose-200 bg-rose-50 px-4 py-3 text-sm font-bold text-rose-700">{error}</div>}
        <div className="grid gap-2 sm:grid-cols-2">
          <Button type="button" variant="secondary" disabled={submitting} onClick={() => setDecision(null)}>Cancel</Button>
          <Button type="submit" variant={decision === "rejected" ? "danger" : "primary"} loading={submitting}>{decision === "rejected" ? "Confirm rejection" : `Confirm ${positiveLabel.toLowerCase()}`}</Button>
        </div>
      </form>
    </Modal>}
  </>;
}
