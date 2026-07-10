import { useEffect, useState } from "react";
import { Eye, Plus } from "lucide-react";
import { Card, ConfirmModal, ManagementHeader, ManagementTable, Modal, Pill } from "../../components/ui";
import { projectsApi } from "../../api/projectsApi";
import { tasksApi } from "../../api/tasksApi";
import { categories } from "../../utils/constants";
import { fmtStatus, formatDateShort, initials, statusTone, todayIso } from "../../utils/format";

function canManageProjects(user) {
  return ["super_admin", "admin", "project_manager"].includes(user.role);
}

function userOptionLabel(person) {
  return person?.name || person?.email || "Unnamed user";
}
function ProjectCreateModal({ create, user, pms, supervisors, onClose }) {
  const defaultProjectManagerId = pms[0]?.id || "";
  const defaultSupervisorId = supervisors[0]?.id || "";
  const hasProjectManagers = pms.length > 0;
  const hasSupervisors = supervisors.length > 0;

  return (
    <Modal title="Create Project" subtitle="Generate a 45-day execution calendar" onClose={onClose}>
      <form className="modal-form two-col" onSubmit={create}>
        <label>
          Project Name
          <input name="name" placeholder="Enter project name" required />
        </label>

        <label>
          Client Name
          <input name="client_name" placeholder="Enter client name" required />
        </label>

        <label className="wide">
          Site Address
          <input name="site_address" placeholder="Enter site address" required />
        </label>

        <label>
          Start Date
          <input name="start_date" type="date" defaultValue={todayIso()} required />
        </label>

        {user.role !== "project_manager" && (
          <label>
            Project Manager
            <select
              name="project_manager_id"
              defaultValue={defaultProjectManagerId}
              required
              disabled={!hasProjectManagers}
            >
              {!hasProjectManagers && <option value="">No project manager available</option>}
              {pms.map((person) => (
                <option key={person.id} value={person.id}>{userOptionLabel(person)}</option>
              ))}
            </select>
          </label>
        )}

        <label>
          Supervisor
          <select
            name="supervisor_id"
            defaultValue={defaultSupervisorId}
            required
            disabled={!hasSupervisors}
          >
            {!hasSupervisors && <option value="">No supervisor available</option>}
            {supervisors.map((person) => (
              <option key={person.id} value={person.id}>{userOptionLabel(person)}</option>
            ))}
          </select>
        </label>

        <button disabled={(user.role !== "project_manager" && !hasProjectManagers) || !hasSupervisors}>
          <Plus size={18} /> Create Project
        </button>
      </form>
    </Modal>
  );
}
function ProjectModal({ project, data, action, user, onClose }) {
  const [confirmDelete, setConfirmDelete] = useState(false);
  const pms = data.users?.filter(u => u.role === "project_manager" && u.active !== false) || [];
  const supervisors = data.users?.filter(u => u.role === "supervisor" && u.active !== false) || [];
  const editable = canManageProjects(user);
  async function updateProject(e) { e.preventDefault(); const payload = Object.fromEntries(new FormData(e.currentTarget)); await action(() => projectsApi.update(project.id, payload), "Project updated"); onClose(); }
  async function deleteProject() { await action(() => projectsApi.remove(project.id), "Project deleted"); setConfirmDelete(false); onClose(); }
  return <Modal title="Project Details" subtitle={editable ? "View and edit project assignment" : "Assigned project overview"} onClose={onClose}><div className="profile-hero"><div className="avatar large">{initials(project.name)}</div><div><h3>{project.name}</h3><p>{project.client_name} - {project.progress}% approved</p></div><Pill tone="green">{project.status}</Pill></div><div className="detail-grid"><article><span>Project Manager</span><strong>{project.project_manager_name}</strong></article><article><span>Supervisor</span><strong>{project.supervisor_name}</strong></article><article><span>Start</span><strong>{formatDateShort(project.start_date)}</strong></article><article><span>Target</span><strong>{formatDateShort(project.target_handover_date)}</strong></article></div>{editable ? <form className="modal-form two-col" onSubmit={updateProject}><label>Project Name<input name="name" defaultValue={project.name} /></label><label>Client Name<input name="client_name" defaultValue={project.client_name} /></label><label className="wide">Site Address<input name="site_address" defaultValue={project.site_address} /></label><label>Status<select name="status" defaultValue={project.status}><option value="active">Active</option><option value="on_hold">On hold</option><option value="completed">Completed</option></select></label>{user.role !== "project_manager" && <label>Project Manager<select name="project_manager_id" defaultValue={project.project_manager_id}>{pms.map(u => <option key={u.id} value={u.id}>{u.name}</option>)}</select></label>}<label>Supervisor<select name="supervisor_id" defaultValue={project.supervisor_id}>{supervisors.map(u => <option key={u.id} value={u.id}>{u.name}</option>)}</select></label><button>Save Project</button><button type="button" className="danger" onClick={() => setConfirmDelete(true)}>Delete Project</button></form> : <div className="info-strip">You can view this project here. Daily task updates are handled from the Today tab.</div>}{confirmDelete && <ConfirmModal title="Delete project?" message={`This will permanently delete ${project.name} and its generated tasks.`} confirmLabel="Delete Project" onClose={() => setConfirmDelete(false)} onConfirm={deleteProject} />}</Modal>;
}

function TaskModal({ task, vendors, action, onClose }) {
  async function save(e) { e.preventDefault(); const f = new FormData(e.currentTarget); const body = Object.fromEntries(f); body.vendor_id = body.vendor_id || null; await action(() => tasksApi.update(task.id, body), "Task saved"); onClose(); }
  return <Modal title="Edit task" subtitle="Task instructions and vendor assignment" onClose={onClose}><form className="modal-form" onSubmit={save}><input name="title" defaultValue={task.title} /><select name="category" defaultValue={task.category}>{categories.map(c => <option key={c}>{c}</option>)}</select><textarea name="description" defaultValue={task.description || ""} placeholder="Task description" /><textarea name="supervisor_instruction" defaultValue={task.supervisor_instruction || ""} placeholder="Supervisor instruction" /><textarea name="pm_instruction" defaultValue={task.pm_instruction || ""} placeholder="PM review instruction" /><input name="proof_required" defaultValue={task.proof_required || ""} placeholder="Proof required" /><input type="date" name="due_date" defaultValue={task.due_date} /><select name="vendor_id" defaultValue={task.vendor_id || ""}><option value="">Unassigned</option>{vendors.map(v => <option key={v.id} value={v.id}>{v.name} - {v.category}</option>)}</select><input name="admin_note" defaultValue={task.admin_note || ""} placeholder="Internal note" /><button>Save task</button></form></Modal>;
}

function TaskList({ tasks, vendors, action }) {
  const [editing, setEditing] = useState(null);
  return <Card><div className="panel-title"><div><p>Daily task control</p><h2>Tasks for selected date</h2></div><Pill>CRUD + vendor assignment</Pill></div><div className="task-list">{tasks.map(t => <button key={t.id} onClick={() => setEditing(t)}><div><b>{t.title}</b><span>{t.category} - Due {formatDateShort(t.due_date)} - {t.vendor?.name || "Vendor unassigned"}</span></div><Pill tone={statusTone(t.status)}>{fmtStatus(t.status)}</Pill></button>)}</div>{editing && <TaskModal task={editing} vendors={vendors} action={action} onClose={() => setEditing(null)} />}</Card>;
}

function ProjectExecution({ project, data, action, user }) {
  const [days, setDays] = useState([]);
  const [date, setDate] = useState(project.start_date);
  const [tasks, setTasks] = useState([]);
  useEffect(() => { projectsApi.days(project.id).then(setDays); }, [project.id]);
  useEffect(() => { projectsApi.tasks(project.id, date).then(setTasks); }, [project.id, date]);
  if (!canManageProjects(user)) return null;
  return <><Card><div className="panel-title"><div><p>45-day calendar</p><h2>Pick a date</h2></div></div><div className="calendar-strip">{days.map(d => <button key={d.day_no} onClick={() => setDate(d.date)} className={date === d.date ? "active" : ""}><span>Day {d.day_no}</span><b>{new Date(`${d.date}T00:00:00`).toLocaleDateString("en-GB", { day: "2-digit", month: "short" })}</b><small>{d.done}/{d.total} done</small></button>)}</div></Card><TaskList tasks={tasks} vendors={data.vendors} action={action} /></>;
}

export function ProjectsPage({ data, user, action }) {
  const [selectedId, setSelectedId] = useState(data.projects[0]?.id || "");
  const [creating, setCreating] = useState(false);
  const [modalProject, setModalProject] = useState(null);

  const selected = data.projects.find((project) => project.id === selectedId);
  const pms = data.users?.filter((item) => item.role === "project_manager" && item.active !== false) || [];
  const supervisors = data.users?.filter((item) => item.role === "supervisor" && item.active !== false) || [];
  const canManage = canManageProjects(user);

  async function create(e) {
    e.preventDefault();

    const form = e.currentTarget;
    const payload = Object.fromEntries(new FormData(form));

    await action(() => projectsApi.create(payload), "Project created");

    form.reset();
    setCreating(false);
  }

  function openProject(project) {
    setSelectedId(project.id);
    setModalProject(project);
  }

  return (
    <div className="stack">
      <ManagementHeader
        eyebrow="Projects"
        title="Projects"
        subtitle={canManage ? "Plan, assign and monitor execution calendars" : "Assigned project progress"}
        actionLabel={canManage ? "Create Project" : ""}
        actionIcon={canManage ? <Plus size={18} /> : null}
        onAction={canManage ? () => setCreating(true) : undefined}
      />

      <ManagementTable
        countLabel="Total Projects"
        count={data.projects.length}
        searchPlaceholder="Search projects?"
        tableClassName="project-table"
      >
            <colgroup>
              <col className="w-[31%]" />
              <col className="w-[15%]" />
              <col className="w-[15%]" />
              <col className="w-[24%]" />
              <col className="w-[8%]" />
              <col className="w-[7%]" />
            </colgroup>
            <thead>
              <tr className="data-row table-head">
                <th scope="col">Project</th>
                <th scope="col">Manager</th>
                <th scope="col">Supervisor</th>
                <th scope="col">Dates</th>
                <th scope="col">Progress</th>
                <th scope="col">Actions</th>
              </tr>
            </thead>
            <tbody>
              {data.projects.map((project) => (
                <tr
                  key={project.id}
                  className={selectedId === project.id ? "data-row selected" : "data-row"}
                  role="button"
                  tabIndex={0}
                  onClick={() => openProject(project)}
                  onKeyDown={(event) => {
                    if (event.key === "Enter" || event.key === " ") openProject(project);
                  }}
                >
                  <td data-label="Project"><b>{project.name}</b><small>{project.client_name}</small></td>
                  <td data-label="Manager">{project.project_manager_name}</td>
                  <td data-label="Supervisor">{project.supervisor_name}</td>
                  <td data-label="Dates">{formatDateShort(project.start_date)} - {formatDateShort(project.target_handover_date)}</td>
                  <td data-label="Progress"><strong>{project.progress}%</strong></td>
                  <td data-label="Actions">
                    <button
                      type="button"
                      className="kebab"
                      aria-label={`Open ${project.name}`}
                      onClick={(event) => {
                        event.stopPropagation();
                        openProject(project);
                      }}
                    >
                      <Eye size={20} />
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
      </ManagementTable>

      {creating && <ProjectCreateModal create={create} user={user} pms={pms} supervisors={supervisors} onClose={() => setCreating(false)} />}
      {modalProject && <ProjectModal project={modalProject} data={data} action={action} user={user} onClose={() => setModalProject(null)} />}
      {selected && <ProjectExecution project={selected} data={data} action={action} user={user} />}
    </div>
  );
}