import { assetUrl } from "../../api/client";
import { tasksApi } from "../../api/tasksApi";
import { Card, Pill } from "../../components/ui";

export function ApprovalsPage({ data, action }) {
  return <Card><div className="panel-title"><div><p>PM approval queue</p><h2>Submitted tasks</h2></div><Pill>{data.review_tasks.length} pending</Pill></div><div className="task-list">{data.review_tasks.map(t => <div className="approval-card" key={t.id}><div><b>{t.title}</b><span>{t.supervisor_note || "No note"}</span>{t.proof_url && <img src={assetUrl(t.proof_url)} alt="Task proof" />}</div><div><button onClick={() => action(() => tasksApi.review(t.id, { action: "approve" }), "Task approved")}>Approve</button><button className="danger" onClick={() => action(() => tasksApi.review(t.id, { action: "reject", rejection_reason: "Needs correction" }), "Task rejected")}>Reject</button></div></div>)}</div></Card>;
}
