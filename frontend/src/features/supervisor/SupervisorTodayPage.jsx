import { useEffect, useState } from "react";
import { tasksApi } from "../../api/tasksApi";
import { Card, Pill } from "../../components/ui";
import { fmtStatus, statusTone } from "../../utils/format";

export function SupervisorTodayPage({ action }) {
  const [tasks, setTasks] = useState([]);
  useEffect(() => { tasksApi.supervisorToday().then(setTasks); }, []);
  async function submit(e, task) { e.preventDefault(); const form = new FormData(e.currentTarget); await action(() => tasksApi.supervisorUpdate(task.id, form), "Update submitted for PM review"); setTasks(await tasksApi.supervisorToday()); }
  return <div className="stack"><Card><div className="panel-title"><div><p>Site supervisor</p><h2>Today + carried-forward tasks</h2></div><Pill>Future dates hidden</Pill></div>{tasks.length === 0 && <p>No tasks assigned for today.</p>}{tasks.map(t => <form className="supervisor-task" key={t.id} onSubmit={(e) => submit(e, t)}><div className="task-top"><Pill>Day {t.day_no} • {t.scheduled_date}</Pill><Pill tone={statusTone(t.status)}>{fmtStatus(t.status)}</Pill></div><h3>{t.title}</h3><p>{t.description}</p><div className="instruction"><b>What you need to do</b><span>{t.supervisor_instruction || "Check work and submit update."}</span></div><div className="instruction"><b>Vendor contact</b><span>{t.vendor ? `${t.vendor.name} • ${t.vendor.contact_person} • ${t.vendor.phone}` : "Vendor not assigned yet. Ask PM before execution."}</span></div><b>Proof required: {t.proof_required || "One clear site photo."}</b><select name="status" defaultValue="submitted"><option value="in_progress">In Progress</option><option value="submitted">Submit for PM approval</option><option value="delayed">Delayed</option><option value="blocked">Blocked</option></select><textarea name="supervisor_note" placeholder="Site note" /><input name="delay_reason" placeholder="Delay/block reason if any" /><input name="proof_url" placeholder="Photo proof link/reference" /><input name="proof_file" type="file" accept="image/*" /><button>Save update</button></form>)}</Card></div>;
}
