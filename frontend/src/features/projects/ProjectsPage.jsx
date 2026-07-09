import { useEffect, useState } from "react";
import { MoreVertical, Plus } from "lucide-react";
import { Card, ManagementHeader, ManagementTable, Modal, Pill } from "../../components/ui";
import { projectsApi } from "../../api/projectsApi";
import { tasksApi } from "../../api/tasksApi";
import { categories } from "../../utils/constants";
import { fmtStatus, formatDateShort, initials, statusTone, todayIso } from "../../utils/format";

function ProjectCreateModal({ create, user, pms, supervisors, onClose }) {
  return <Modal title="Create Project" subtitle="Generate a 45-day execution calendar" onClose={onClose}><form className="modal-form two-col" onSubmit={create}><label>Project Name<input name="name" placeholder="Enter project name" required /></label><label>Client Name<input name="client_name" placeholder="Enter client name" required /></label><label className="wide">Site Address<input name="site_address" placeholder="Enter site address" required /></label><label>Start Date<input name="start_date" type="date" defaultValue={todayIso()} required /></label>{user.role !== "project_manager" && <label>Project Manager<select name="project_manager_id" required>{pms.map(u => <option key={u.id} value={u.id}>{u.name}</option>)}</select></label>}<label>Supervisor<select name="supervisor_id" required>{supervisors.map(u => <option key={u.id} value={u.id}>{u.name}</option>)}</select></label><button><Plus size={18} /> Create Project</button></form></Modal>;
}

function ProjectEditModal({ project, data, action, user, onClose }) {
  const pms = data.users?.filter(u => u.role === "project_manager") || [];
  const supervisors = data.users?.filter(u => u.role === "supervisor") || [];
  async function updateProject(e) { e.preventDefault(); const payload = Object.fromEntries(new FormData(e.currentTarget)); await action(() => projectsApi.update(project.id, payload), "Project updated"); onClose(); }
  async function deleteProject() { if (confirm("Delete this project?")) { await action(() => projectsApi.remove(project.id), "Project deleted"); onClose(); } }
  return <Modal title="Project Details" subtitle="Project profile and assignment" onClose={onClose}><div className="profile-hero"><div className="avatar large">{initials(project.name)}</div><div><h3>{project.name}</h3><p>{project.client_name} • {project.progress}% approved</p></div><Pill tone="green">{project.status}</Pill></div><div className="detail-grid"><article><span>Project Manager</span><strong>{project.project_manager_name}</strong></article><article><span>Supervisor</span><strong>{project.supervisor_name}</strong></article><article><span>Start</span><strong>{formatDateShort(project.start_date)}</strong></article><article><span>Target</span><strong>{formatDateShort(project.target_handover_date)}</strong></article></div><form className="modal-form two-col" onSubmit={updateProject}><label>Project Name<input name="name" defaultValue={project.name} /></label><label>Client Name<input name="client_name" defaultValue={project.client_name} /></label><label className="wide">Site Address<input name="site_address" defaultValue={project.site_address} /></label><label>Status<select name="status" defaultValue={project.status}><option value="active">Active</option><option value="on_hold">On hold</option><option value="completed">Completed</option></select></label>{user.role !== "project_manager" && <label>Project Manager<select name="project_manager_id" defaultValue={project.project_manager_id}>{pms.map(u => <option key={u.id} value={u.id}>{u.name}</option>)}</select></label>}<label>Supervisor<select name="supervisor_id" defaultValue={project.supervisor_id}>{supervisors.map(u => <option key={u.id} value={u.id}>{u.name}</option>)}</select></label><button>Save Project</button><button type="button" className="danger" onClick={deleteProject}>Delete Project</button></form></Modal>;
}

function TaskModal({ task, vendors, action, onClose }) {
  async function save(e) { e.preventDefault(); const f = new FormData(e.currentTarget); const body = Object.fromEntries(f); body.vendor_id = body.vendor_id || null; await action(() => tasksApi.update(task.id, body), "Task saved"); onClose(); }
  return <Modal title="Edit task" onClose={onClose}><form className="modal-form" onSubmit={save}><input name="title" defaultValue={task.title} /><select name="category" defaultValue={task.category}>{categories.map(c => <option key={c}>{c}</option>)}</select><textarea name="description" defaultValue={task.description || ""} placeholder="Task description" /><textarea name="supervisor_instruction" defaultValue={task.supervisor_instruction || ""} placeholder="Supervisor instruction" /><textarea name="pm_instruction" defaultValue={task.pm_instruction || ""} placeholder="PM review instruction" /><input name="proof_required" defaultValue={task.proof_required || ""} placeholder="Proof required" /><input type="date" name="due_date" defaultValue={task.due_date} /><select name="vendor_id" defaultValue={task.vendor_id || ""}><option value="">Unassigned</option>{vendors.map(v => <option key={v.id} value={v.id}>{v.name} • {v.category}</option>)}</select><input name="admin_note" defaultValue={task.admin_note || ""} placeholder="Internal note" /><button>Save task</button></form></Modal>;
}

function TaskList({ tasks, vendors, action }) {
  const [editing, setEditing] = useState(null);
  return <Card><div className="panel-title"><div><p>Daily task control</p><h2>Tasks for selected date</h2></div><Pill>CRUD + vendor assignment</Pill></div><div className="task-list">{tasks.map(t => <button key={t.id} onClick={() => setEditing(t)}><div><b>{t.title}</b><span>{t.category} • Due {t.due_date} • {t.vendor?.name || "Vendor unassigned"}</span></div><Pill tone={statusTone(t.status)}>{fmtStatus(t.status)}</Pill></button>)}</div>{editing && <TaskModal task={editing} vendors={vendors} action={action} onClose={() => setEditing(null)} />}</Card>;
}

function ProjectDetail({ project, data, action, user }) {
  const [days, setDays] = useState([]);
  const [date, setDate] = useState(project.start_date);
  const [tasks, setTasks] = useState([]);
  const pms = data.users?.filter(u => u.role === "project_manager") || [];
  const supervisors = data.users?.filter(u => u.role === "supervisor") || [];
  useEffect(() => { projectsApi.days(project.id).then(setDays); }, [project.id]);
  useEffect(() => { projectsApi.tasks(project.id, date).then(setTasks); }, [project.id, date]);
  async function updateProject(e) { e.preventDefault(); await action(() => projectsApi.update(project.id, Object.fromEntries(new FormData(e.currentTarget))), "Project updated"); }
  return <><Card><div className="panel-title"><div><p>Project control</p><h2>Edit project</h2></div><button className="danger" onClick={() => confirm("Delete this project?") && action(() => projectsApi.remove(project.id), "Project deleted")}>Delete</button></div><form className="smart-form" onSubmit={updateProject}><input name="name" defaultValue={project.name} /><input name="client_name" defaultValue={project.client_name} /><input name="site_address" defaultValue={project.site_address} /><select name="status" defaultValue={project.status}><option value="active">Active</option><option value="on_hold">On hold</option><option value="completed">Completed</option></select>{user.role !== "project_manager" && <select name="project_manager_id" defaultValue={project.project_manager_id}>{pms.map(u => <option key={u.id} value={u.id}>{u.name}</option>)}</select>}<select name="supervisor_id" defaultValue={project.supervisor_id}>{supervisors.map(u => <option key={u.id} value={u.id}>{u.name}</option>)}</select><button>Save project</button></form></Card><Card><div className="panel-title"><div><p>45-day calendar</p><h2>Pick a date</h2></div></div><div className="calendar-strip">{days.map(d => <button key={d.day_no} onClick={() => setDate(d.date)} className={date === d.date ? "active" : ""}><span>Day {d.day_no}</span><b>{new Date(`${d.date}T00:00:00`).toLocaleDateString("en-GB", { day: "2-digit", month: "short" })}</b><small>{d.done}/{d.total} done</small></button>)}</div></Card><TaskList tasks={tasks} vendors={data.vendors} action={action} /></>;
}

export function ProjectsPage({ data, user, action }) {
  const [selectedId, setSelectedId] = useState(data.projects[0]?.id || "");
  const [creating, setCreating] = useState(false);
  const [editingProject, setEditingProject] = useState(null);
  const selected = data.projects.find(p => p.id === selectedId);
  const pms = data.users?.filter(u => u.role === "project_manager") || [];
  const supervisors = data.users?.filter(u => u.role === "supervisor") || [];
  async function create(e) { e.preventDefault(); const form = e.currentTarget; const payload = Object.fromEntries(new FormData(form)); await action(() => projectsApi.create(payload), "Project created"); form.reset(); setCreating(false); }
  return <div className="stack"><ManagementHeader eyebrow="Projects" title="Projects" subtitle="Plan, assign and monitor execution calendars" actionLabel="Create Project" actionIcon={<Plus size={18} />} onAction={() => setCreating(true)} /><ManagementTable countLabel="Total Projects" count={data.projects.length} searchPlaceholder="Search projects?"><div className="data-table project-table"><div className="data-row table-head"><span>Project</span><span>Manager</span><span>Supervisor</span><span>Dates</span><span>Progress</span><span>Actions</span></div>{data.projects.map(p => <button className={selectedId === p.id ? "data-row selected" : "data-row"} key={p.id} onClick={() => { setSelectedId(p.id); setEditingProject(p); }}><span><b>{p.name}</b><small>{p.client_name}</small></span><span>{p.project_manager_name}</span><span>{p.supervisor_name}</span><span>{formatDateShort(p.start_date)} - {formatDateShort(p.target_handover_date)}</span><span><strong>{p.progress}%</strong></span><span><span className="kebab"><MoreVertical size={20} /></span></span></button>)}</div></ManagementTable>{creating && <ProjectCreateModal create={create} user={user} pms={pms} supervisors={supervisors} onClose={() => setCreating(false)} />}{editingProject && <ProjectEditModal project={editingProject} data={data} action={action} user={user} onClose={() => setEditingProject(null)} />}{selected && <ProjectDetail project={selected} data={data} action={action} user={user} />}</div>;
}
