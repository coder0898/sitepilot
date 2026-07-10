import { useState } from "react";
import { assetUrl } from "../../api/client";
import { tasksApi } from "../../api/tasksApi";
import { Card, ConfirmModal, Pill } from "../../components/ui";

function ApprovalCard({ task, action }) {
  const [rejecting, setRejecting] = useState(false);
  const [reason, setReason] = useState("");

  async function reject() {
    const rejectionReason = reason.trim();
    if (!rejectionReason) return;
    await action(() => tasksApi.review(task.id, { action: "reject", rejection_reason: rejectionReason }), "Task rejected");
    setRejecting(false);
    setReason("");
  }

  return (
    <div className="approval-card">
      <div>
        <b>{task.title}</b>
        <span>{task.supervisor_note || "No supervisor note submitted"}</span>
        {task.delay_reason && <span>Delay/block reason: {task.delay_reason}</span>}
        {task.proof_url && <img src={assetUrl(task.proof_url)} alt="Task proof" />}
      </div>
      <div>
        <button onClick={() => action(() => tasksApi.review(task.id, { action: "approve" }), "Task approved")}>Approve</button>
        <button className="danger" onClick={() => setRejecting(true)}>Reject</button>
      </div>

      {rejecting && (
        <ConfirmModal
          title="Reject task?"
          message="Add a clear reason. The supervisor will see this reason and resubmit after correction."
          confirmLabel="Reject Task"
          onClose={() => setRejecting(false)}
          onConfirm={reject}
          confirmDisabled={!reason.trim()}
        >
          <textarea
            className="confirm-textarea"
            value={reason}
            onChange={(event) => setReason(event.target.value)}
            placeholder="Mandatory rejection reason"
            autoFocus
          />
        </ConfirmModal>
      )}
    </div>
  );
}

export function ApprovalsPage({ data, action }) {
  return (
    <Card>
      <div className="panel-title">
        <div>
          <p>PM approval queue</p>
          <h2>Submitted tasks</h2>
        </div>
        <Pill>{data.review_tasks.length} pending</Pill>
      </div>
      <div className="task-list">
        {data.review_tasks.length === 0 && <p>No submitted tasks waiting for review.</p>}
        {data.review_tasks.map((task) => <ApprovalCard key={task.id} task={task} action={action} />)}
      </div>
    </Card>
  );
}
