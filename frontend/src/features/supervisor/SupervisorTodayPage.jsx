import { useEffect, useMemo, useState } from "react";
import { Upload } from "lucide-react";
import { tasksApi } from "../../api/tasksApi";
import { Card, Modal, Pill } from "../../components/ui";
import { fmtStatus, statusTone } from "../../utils/format";

function countByStatus(tasks, status) {
  return tasks.filter((task) => task.status === status).length;
}

function TaskUpdateForm({ task, onSubmit }) {
  const isSubmitted = task.status === "submitted";
  const isApproved = task.status === "completed";

  return (
    <form className="supervisor-task" onSubmit={(event) => onSubmit(event, task)}>
      <div className="task-top">
        <Pill>Day {task.day_no} - {task.scheduled_date}</Pill>
        <Pill tone={statusTone(task.status)}>{fmtStatus(task.status)}</Pill>
      </div>

      <h3>{task.title}</h3>
      <p>{task.description}</p>

      {task.status === "rejected" && task.rejection_reason && (
        <div className="rejection-box">
          <b>PM rejection reason</b>
          <span>{task.rejection_reason}</span>
        </div>
      )}

      {task.supervisor_note && (
        <div className="instruction">
          <b>Previous site note</b>
          <span>{task.supervisor_note}</span>
        </div>
      )}

      {task.proof_url && (
        <div className="instruction">
          <b>Previous proof</b>
          <a href={task.proof_url} target="_blank" rel="noreferrer">Open submitted proof</a>
        </div>
      )}

      <div className="instruction">
        <b>What you need to do</b>
        <span>{task.supervisor_instruction || "Check work, coordinate with vendor, add note and proof."}</span>
      </div>

      <div className="instruction">
        <b>Vendor contact</b>
        <span>{task.vendor ? `${task.vendor.name} - ${task.vendor.contact_person} - ${task.vendor.phone}` : "Vendor not assigned yet. Ask PM before execution."}</span>
      </div>

      <b>Proof required: {task.proof_required || "One clear site photo or proof reference."}</b>

      {isApproved ? (
        <div className="info-strip">This task is approved. No further update is required.</div>
      ) : isSubmitted ? (
        <div className="info-strip">Submitted for PM approval. You can update again only if PM rejects it.</div>
      ) : (
        <>
          <select name="status" defaultValue="submitted">
            <option value="in_progress">In Progress</option>
            <option value="submitted">Submit for PM approval</option>
            <option value="delayed">Delayed</option>
            <option value="blocked">Blocked</option>
          </select>
          <textarea name="supervisor_note" placeholder="Site note" defaultValue={task.supervisor_note || ""} />
          <input name="delay_reason" placeholder="Delay/block reason if any" defaultValue={task.delay_reason || ""} />
          <input name="proof_url" placeholder="Photo proof link/reference" defaultValue={task.proof_url || ""} />
          <label className="file-input">
            <Upload size={18} />
            Upload proof photo
            <input name="proof_file" type="file" accept="image/*" />
          </label>
          <button>Save update</button>
        </>
      )}
    </form>
  );
}

export function SupervisorTodayPage({ action }) {
  const [tasks, setTasks] = useState([]);
  const [selectedTask, setSelectedTask] = useState(null);

  useEffect(() => {
    tasksApi.supervisorToday().then(setTasks);
  }, []);

  const stats = useMemo(() => ([
    ["Approved", countByStatus(tasks, "completed")],
    ["In Progress", countByStatus(tasks, "in_progress")],
    ["Delayed", countByStatus(tasks, "delayed") + countByStatus(tasks, "blocked")],
    ["Rejected", countByStatus(tasks, "rejected")],
    ["Pending Approval", countByStatus(tasks, "submitted")],
    ["Not Started", countByStatus(tasks, "pending")],
  ]), [tasks]);

  async function submit(event, task) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    await action(() => tasksApi.supervisorUpdate(task.id, form), "Update submitted for PM review");
    const refreshedTasks = await tasksApi.supervisorToday();
    setTasks(refreshedTasks);
    setSelectedTask(null);
  }

  return (
    <div className="stack">
      <Card>
        <div className="panel-title">
          <div>
            <p>Site supervisor</p>
            <h2>Today + carried-forward tasks</h2>
          </div>
          <Pill>Future dates hidden</Pill>
        </div>

        <div className="status-summary-grid">
          {stats.map(([label, value]) => (
            <article key={label}>
              <span>{label}</span>
              <strong>{value}</strong>
            </article>
          ))}
        </div>

        {tasks.length === 0 && <p>No tasks assigned for today.</p>}
        <div className="task-list supervisor-task-list">
          {tasks.map((task) => (
            <button key={task.id} type="button" onClick={() => setSelectedTask(task)}>
              <div>
                <b>{task.title}</b>
                <span>Day {task.day_no} - {task.scheduled_date} - {task.vendor?.name || "Vendor unassigned"}</span>
                {task.status === "rejected" && task.rejection_reason && <span>Rejected: {task.rejection_reason}</span>}
              </div>
              <Pill tone={statusTone(task.status)}>{fmtStatus(task.status)}</Pill>
            </button>
          ))}
        </div>
      </Card>

      {selectedTask && (
        <Modal title="Task Details" subtitle="Update task status, notes and proof" onClose={() => setSelectedTask(null)}>
          <TaskUpdateForm task={selectedTask} onSubmit={submit} />
        </Modal>
      )}
    </div>
  );
}
