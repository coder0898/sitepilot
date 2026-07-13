import { useEffect, useMemo, useState } from "react";
import { Activity, AlertTriangle, Bell, BriefcaseBusiness, CalendarDays, CheckCircle2, CircleDot, ClipboardList, Clock3, LayoutTemplate, Plus, RefreshCw, Trash2, UserRound, Users } from "lucide-react";
import { executionApi } from "../../api/executionApi";
import { ConfirmModal, Modal, Pill } from "../../components/ui";

const empty = { projects: [], days: [], tasks: [], users: [], contractors: [], relationships: [], templates: [] };
const prettyStatus = value => String(value || "assigned").replaceAll("_", " ");

export function ExecutionPage({ user, action }) {
  const [data, setData] = useState(empty);
  const [projectId, setProjectId] = useState("");
  const [form, setForm] = useState(null);
  const [selectedTask, setSelectedTask] = useState(null);
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [view, setView] = useState("schedule");
  const canManage = user.role !== "supervisor";

  async function load() {
    const next = await executionApi.get();
    setData({ ...empty, ...next });
    setSelectedTask(current => current ? next.tasks.find(task => task.id === current.id) || null : null);
    setProjectId(current => next.projects.some(project => project.id === current) ? current : next.projects[0]?.id || "");
  }
  useEffect(() => { load().catch(() => {}); }, []);

  async function perform(fn, message) {
    let ok = false;
    const result = await action(async () => { await fn(); ok = true; }, message);
    if (ok) { setForm(null); setSelectedTask(null); await load(); }
    return result || { ok };
  }

  const project = data.projects.find(item => item.id === projectId);
  const days = data.days.filter(item => item.project_id === projectId);
  const tasks = data.tasks.filter(item => item.project_id === projectId);
  const overdueTasks = tasks.filter(task => task.is_overdue);
  const pendingDelayTasks = tasks.filter(task => task.active_delay_report);
  const supervisors = data.users.filter(item => item.role === "supervisor");
  const pms = data.users.filter(item => item.role === "project_manager");
  const mains = data.contractors.filter(item => item.engagement_type === "main");
  const independent = data.contractors.filter(item => item.engagement_type === "independent");
  const subsFor = id => data.relationships.filter(item => item.main_contractor_id === id).map(item => data.contractors.find(vendor => vendor.id === item.subcontractor_id)).filter(Boolean);
  const progress = tasks.length ? Math.round(tasks.filter(task => ["approved", "completed"].includes(task.status)).length / tasks.length * 100) : 0;
  const notifications = tasks.flatMap(task => task.notifications.map(note => ({ ...note, taskTitle: task.title })));
  const assignedCompanies = new Set(tasks.flatMap(task => [task.assigned_contractor_id, task.assigned_subcontractor_id]).filter(Boolean)).size;
  const supervisor = data.users.find(item => item.id === project?.supervisor_id);
  const pm = data.users.find(item => item.id === project?.project_manager_id);
  const statusCounts = useMemo(() => tasks.reduce((result, task) => ({ ...result, [task.status]: (result[task.status] || 0) + 1 }), {}), [tasks]);

  async function createProject(event) {
    event.preventDefault();
    const payload = Object.fromEntries(new FormData(event.currentTarget));
    payload.duration_days = Number(payload.duration_days);
    payload.template_id = payload.template_id || null;
    payload.project_manager_id = payload.project_manager_id || null;
    await perform(() => executionApi.createProject(payload), "Three-day project created");
  }
  async function saveTask(event) {
    event.preventDefault();
    const payload = Object.fromEntries(new FormData(event.currentTarget));
    payload.assigned_contractor_id = payload.assigned_contractor_id || null;
    payload.assigned_subcontractor_id = payload.assigned_subcontractor_id || null;
    payload.material_reminder = payload.material_reminder === "on";
    payload.reminder_lead_days = 1;
    await perform(() => selectedTask ? executionApi.updateTask(selectedTask.id, payload) : executionApi.createTask(payload), selectedTask ? "Task updated" : "Task created and notification preview generated");
  }
  async function createTemplate(event) {
    event.preventDefault();
    const fields = new FormData(event.currentTarget);
    const duration = Number(fields.get("duration_days"));
    const templateTasks = [];
    for (let day = 1; day <= duration; day += 1) {
      String(fields.get(`day_${day}`) || "").split("\n").map(item => item.trim()).filter(Boolean).forEach(title => templateTasks.push({ day_no: day, title, category: "General", priority: "medium" }));
    }
    await perform(() => executionApi.createTemplate({ name: fields.get("name"), project_type: fields.get("project_type"), duration_days: duration, tasks: templateTasks }), "Execution template created");
  }
  async function remove() { await perform(() => executionApi.deleteTask(selectedTask.id), "Task deleted"); setConfirmDelete(false); }
  async function saveProject(event) { event.preventDefault(); await perform(() => executionApi.updateProject(project.id, Object.fromEntries(new FormData(event.currentTarget))), "Project updated"); }
  async function deleteProject() { await perform(() => executionApi.deleteProject(project.id), "Project deleted"); setProjectId(""); }
  async function changeStatus(status) { await perform(() => executionApi.updateStatus(selectedTask.id, status), `Task marked ${prettyStatus(status)}`); }
  async function submitWork(event) { event.preventDefault(); await perform(() => executionApi.submitTask(selectedTask.id, new FormData(event.currentTarget)), "Work submitted for PM review"); }
  async function reviewTask(actionName, reason) { await perform(() => executionApi.reviewTask(selectedTask.id, actionName, reason), actionName === "approve" ? "Work approved" : "Work rejected for correction"); }
  async function reportDelay(event) { event.preventDefault(); const payload = Object.fromEntries(new FormData(event.currentTarget)); await perform(() => executionApi.reportDelay(selectedTask.id, payload), "Delay reported to the Project Manager"); }
  async function rescheduleTask(payload) { return perform(() => executionApi.rescheduleTask(selectedTask.id, payload), "Task rescheduled with audit history"); }
  function openTask(day) { setSelectedTask(null); setForm({ type: "task", day }); }

  return (
    <div className="exec-dashboard">
      <section className="exec-welcome">
        <div><p>Good morning, {user.name.split(" ")[0]}!</p><small>{project?.name || "Select or create an execution project"}{project?.template_name ? ` · ${project.template_name}` : ""}</small></div>
        <div className="exec-welcome-actions"><button className="exec-refresh-button secondary-button" type="button" onClick={() => load()}><RefreshCw size={17}/> Refresh</button>
          <label><BriefcaseBusiness size={16}/><select value={projectId} onChange={event => setProjectId(event.target.value)}><option value="">Select project</option>{data.projects.map(item => <option value={item.id} key={item.id}>{item.name}</option>)}</select></label>
          {user.role === "super_admin" && <button className="exec-icon-button" onClick={() => setView(view === "templates" ? "schedule" : "templates")} aria-label="Execution templates"><LayoutTemplate/></button>}
          {canManage && project && <button className="secondary-button" onClick={() => setForm("project-settings")}>Edit project</button>}{canManage && <button className="flex" onClick={() => setForm("project")}><Plus/> New project</button>}
        </div>
      </section>

      {view === "templates" && user.role === "super_admin" ? <TemplateView templates={data.templates} open={() => setForm("template")}/> : <>
        <section className="exec-metrics">
          <Metric icon={<ClipboardList/>} label="Total tasks" value={tasks.length} helper={`${tasks.filter(task => task.status === "completed").length} completed`} tone="blue"/>
          <Metric icon={<Clock3/>} label="Assigned tasks" value={statusCounts.assigned || 0} helper="Ready to start" tone="orange"/>
          <Metric icon={<AlertTriangle/>} label="Overdue tasks" value={overdueTasks.length} helper={overdueTasks.length ? "Action required" : "Schedule on track"} tone="red"/>
          <Metric icon={<Bell/>} label="Notification previews" value={notifications.length} helper={`${notifications.filter(note => note.status === "missing_phone").length} missing phone`} tone="red"/>
          <Metric icon={<Activity/>} label="Project progress" value={`${progress}%`} helper={`${project?.duration_days || 3}-day schedule`} tone="green" progress={progress}/>
          <Metric icon={<Users/>} label="Assigned companies" value={assignedCompanies} helper="Contractors on tasks" tone="violet"/>
        </section>

        {project ? <>
          {overdueTasks.length > 0 && <section className="rounded-[18px] border border-rose-300 bg-gradient-to-r from-rose-50 to-amber-50 p-4 shadow-[0_12px_30px_rgba(190,24,93,0.08)]">
            <div className="flex flex-wrap items-start justify-between gap-3">
              <div><p className="m-0 text-[11px] font-black uppercase tracking-[0.14em] text-rose-700">Attention required</p><h3 className="mt-1 font-serif text-xl text-rose-950">{overdueTasks.length} overdue {overdueTasks.length === 1 ? "task" : "tasks"}</h3><p className="mt-1 text-sm text-rose-800">These tasks passed their active working date and are not submitted or approved.</p></div>
              <Pill tone="red">PM action</Pill>
            </div>
            <div className="mt-4 grid gap-2 md:grid-cols-2 xl:grid-cols-3">{overdueTasks.map(task => <button type="button" key={task.id} onClick={() => setSelectedTask(task)} className="flex min-w-0 items-center justify-between gap-3 rounded-xl border border-rose-200 bg-white px-4 py-3 text-left text-slate-900 shadow-none transition hover:-translate-y-0.5 hover:border-rose-400 hover:bg-white">
              <span className="min-w-0"><strong className="block truncate text-sm">{task.title}</strong><small className="mt-1 block text-xs text-slate-500">Day {task.day_no} · planned {new Date(task.effective_date + "T00:00:00").toLocaleDateString("en-GB", { day:"2-digit", month:"short" })}</small></span>
              <span className="shrink-0 rounded-full bg-rose-100 px-3 py-1 text-xs font-black text-rose-700">{task.overdue_days}d overdue</span>
            </button>)}</div>
          </section>}
          {pendingDelayTasks.length > 0 && <section className="rounded-[18px] border border-amber-300 bg-amber-50 p-4 shadow-[0_12px_30px_rgba(180,83,9,0.08)]">
            <div className="flex flex-wrap items-start justify-between gap-3">
              <div><p className="m-0 text-[11px] font-black uppercase tracking-[0.14em] text-amber-700">Delay reports</p><h3 className="mt-1 font-serif text-xl text-amber-950">{pendingDelayTasks.length} awaiting PM confirmation</h3><p className="mt-1 text-sm text-amber-800">Supervisor proposals do not change the official task date until the PM confirms a reschedule.</p></div>
              <Pill tone="orange">Review required</Pill>
            </div>
            <div className="mt-4 grid gap-2 md:grid-cols-2 xl:grid-cols-3">{pendingDelayTasks.map(task => <button type="button" key={task.id} onClick={() => setSelectedTask(task)} className="flex min-w-0 items-center justify-between gap-3 rounded-xl border border-amber-200 bg-white px-4 py-3 text-left text-slate-900 shadow-none transition hover:-translate-y-0.5 hover:border-amber-400">
              <span className="min-w-0"><strong className="block truncate text-sm">{task.title}</strong><small className="mt-1 block text-xs text-slate-500">{task.active_delay_report.category.replaceAll("_", " ")} · proposed {new Date(task.active_delay_report.proposed_date + "T00:00:00").toLocaleDateString("en-GB", { day:"2-digit", month:"short" })}</small></span>
              <span className="shrink-0 rounded-full bg-amber-100 px-3 py-1 text-xs font-black text-amber-800">Pending</span>
            </button>)}</div>
          </section>}
          <div className="exec-primary-grid">
            <section className="exec-calendar-card">
              <header><div><h3>3-Day Execution Calendar</h3><span>{project.client_name} · {project.location}</span></div><Pill tone="blue">{project.status}</Pill></header>
              <div className="exec-day-grid">{days.map(day => <DayColumn key={day.id} day={day} tasks={tasks.filter(task => task.day_id === day.id)} canManage={canManage} add={() => openTask(day)} select={setSelectedTask}/>)}</div>
              <footer><span className="legend assigned">Assigned</span><span className="legend completed">Completed</span><span className="legend high">High priority</span></footer>
            </section>
            <section className="exec-activity-card">
              <header><h3>Notification Activity</h3><span>Preview mode</span></header>
              <div>{notifications.slice(0, 7).map(note => <article key={note.id}><span className={`exec-activity-icon ${note.status}`}><Bell/></span><div><strong>{note.notification_type === "material_reminder" ? "Material reminder" : note.recipient_name}</strong><p>{note.taskTitle}</p><small>{note.recipient_name} · {note.recipient_type} · {note.phone || "Phone missing"}</small></div><Pill tone={["preview", "scheduled"].includes(note.status) ? "green" : "orange"}>{note.status}</Pill></article>)}{!notifications.length && <EmptySmall text="Task notifications will appear here."/>}</div>
            </section>
          </div>

          <section className="exec-secondary-grid">
            <article className="exec-status-card"><header><h3>Task Status Overview</h3><strong>{tasks.length}</strong></header><div className="status-ring" style={{ "--progress": `${progress * 3.6}deg` }}><span>{progress}%<small>Complete</small></span></div><div className="status-list">{Object.entries(statusCounts).map(([statusName, count]) => <p key={statusName}><span className={`status-dot ${statusName}`}></span>{prettyStatus(statusName)}<strong>{count}</strong></p>)}{!tasks.length && <p>No tasks yet</p>}</div></article>
            <article className="exec-team-card"><header><h3>Project Team</h3><span>Current assignments</span></header><div><TeamMember icon={<UserRound/>} name={pm?.name || user.name} role="Project Manager" phone={pm?.phone}/><TeamMember icon={<Users/>} name={supervisor?.name || "Not assigned"} role="Site Supervisor" phone={supervisor?.phone}/></div></article>
          </section>

          {canManage && <section className="exec-quick-actions"><h3>Quick Actions</h3><div><button onClick={() => openTask(days[0])} disabled={!days[0]}><Plus/><span>Add task</span></button><button onClick={() => setForm("project")}><CalendarDays/><span>New project</span></button>{user.role === "super_admin" && <button onClick={() => setView("templates")}><LayoutTemplate/><span>Templates</span></button>}</div></section>}
        </> : <section className="empty-execution"><CalendarDays/><h3>Create your first three-day project</h3><p>The scheduler will generate Day 1, Day 2 and Day 3 automatically.</p>{canManage && <button onClick={() => setForm("project")}><Plus/> Create project</button>}</section>}
      </>}

      {form === "project-settings" && project && <ProjectSettingsModal project={project} pms={pms} supervisors={supervisors} submit={saveProject} remove={deleteProject} close={() => setForm(null)}/>} 
      {form === "project" && <ProjectModal user={user} pms={pms} supervisors={supervisors} templates={data.templates} submit={createProject} close={() => setForm(null)}/>} 
      {form?.type === "task" && <TaskModal project={project} day={form.day} task={null} supervisors={supervisors} mains={[...mains, ...independent]} subsFor={subsFor} submit={saveTask} close={() => setForm(null)}/>} 
      {selectedTask && !["reschedule","delay-report"].includes(form) && <TaskDetail task={selectedTask} user={user} edit={() => setForm({ type: "edit", day: days.find(day => day.id === selectedTask.day_id) })} reportDelay={() => setForm("delay-report")} reschedule={() => setForm("reschedule")} remove={() => setConfirmDelete(true)} close={() => setSelectedTask(null)} canManage={canManage} onStatus={changeStatus} onSubmit={submitWork} onReview={reviewTask}/>} 
      {form?.type === "edit" && selectedTask && <TaskModal project={project} day={form.day} task={selectedTask} supervisors={supervisors} mains={[...mains, ...independent]} subsFor={subsFor} submit={saveTask} close={() => setForm(null)}/>} 
      {form === "delay-report" && selectedTask && <DelayReportModal task={selectedTask} submit={reportDelay} close={() => setForm(null)}/>} 
      {form === "reschedule" && selectedTask && <RescheduleTaskModal task={selectedTask} submit={rescheduleTask} close={() => setForm(null)}/>} 
      {form === "template" && <TemplateModal submit={createTemplate} close={() => setForm(null)}/>} 
      {confirmDelete && <ConfirmModal title="Delete task?" message="This permanently removes the task and its notification previews." confirmLabel="Delete task" onClose={() => setConfirmDelete(false)} onConfirm={remove}/>} 
    </div>
  );
}

function Metric({ icon, label, value, helper, tone, progress }) { return <article className={`exec-metric ${tone}`}><div><span>{icon}</span><small>{label}</small></div><strong>{value}</strong><p>{helper}</p>{progress !== undefined && <i><b style={{ width: `${progress}%` }}></b></i>}</article>; }
function DayColumn({ day, tasks, canManage, add, select }) {
  return <article className="exec-day"><header><small>Day {day.day_no}</small><strong>{new Date(day.scheduled_date + "T00:00:00").toLocaleDateString("en-GB", { day: "2-digit", month: "short" })}</strong></header><div>
    {tasks.map(task => <button className={task.is_overdue ? "!border-rose-300 !bg-rose-50" : task.rescheduled_date ? "!border-amber-300 !bg-amber-50" : ""} key={task.id} onClick={() => select(task)}>
      <span className={"task-pin " + (task.is_overdue ? "high" : task.priority)}></span>
      <div><strong>{task.title}</strong><small>{task.subcontractor_name || task.contractor_name || "Internal task"}</small>{task.rescheduled_date && <small className="!font-bold !text-amber-700">Revised · {new Date(task.rescheduled_date + "T00:00:00").toLocaleDateString("en-GB", { day:"2-digit", month:"short" })}</small>}</div>
      <Pill tone={task.is_overdue ? "red" : task.status === "completed" ? "green" : task.priority === "high" ? "orange" : "blue"}>{task.is_overdue ? "Overdue " + task.overdue_days + "d" : prettyStatus(task.status)}</Pill>
    </button>)}
    {canManage && <button className="exec-add-task" onClick={add}><Plus/> Add task</button>}
    {!tasks.length && !canManage && <EmptySmall text="No tasks planned"/>}
  </div></article>;
}function TeamMember({ icon, name, role, phone }) { return <article><span>{icon}</span><div><strong>{name}</strong><small>{role}</small><p>{phone || "Phone not added"}</p></div></article>; }
function EmptySmall({ text }) { return <div className="exec-empty-small"><CircleDot/><span>{text}</span></div>; }

function ProjectSettingsModal({ project, pms, supervisors, submit, remove, close }) { const [confirming, setConfirming] = useState(false); return <Modal title="Edit project" subtitle="Update ownership and lifecycle status" onClose={close}><form className="modal-form two-col" onSubmit={submit}><label>Project name<input name="name" defaultValue={project.name} required/></label><label>Client<input name="client_name" defaultValue={project.client_name} required/></label><label>Location<input name="location" defaultValue={project.location} required/></label><label>Area<input name="area" defaultValue={project.area || ""}/></label><label>Project Manager<select name="project_manager_id" defaultValue={project.project_manager_id} required>{pms.map(item => <option value={item.id} key={item.id}>{item.name}</option>)}</select></label><label>Supervisor<select name="supervisor_id" defaultValue={project.supervisor_id} required>{supervisors.map(item => <option value={item.id} key={item.id}>{item.name}</option>)}</select></label><label>Status<select name="status" defaultValue={project.status}><option value="active">Active</option><option value="on_hold">On hold</option><option value="completed">Completed</option><option value="cancelled">Cancelled</option></select></label><button className="full-field">Save project</button><button type="button" className="full-field danger" onClick={() => setConfirming(true)}>Delete project and schedule</button></form>{confirming && <ConfirmModal title="Delete project?" message="This permanently deletes the project, its days, tasks, proofs, and notification previews." confirmLabel="Delete project" onClose={() => setConfirming(false)} onConfirm={remove}/>}</Modal>; }function ProjectModal({ user, pms, supervisors, templates, submit, close }) { const [templateId, setTemplateId] = useState(templates[0]?.id || ""); const selected = templates.find(item => item.id === templateId); return <Modal title="Create project from template" subtitle="Standard tasks will be generated automatically. Add task is only for exceptions." onClose={close}><form className="modal-form two-col" onSubmit={submit}><label className="full-field">Execution template<select name="template_id" value={templateId} onChange={event => setTemplateId(event.target.value)} required><option value="" disabled>Select a template</option>{templates.map(template => <option value={template.id} key={template.id}>{template.name} · {template.duration_days} days · {template.tasks.length} tasks</option>)}</select></label>{selected && <div className="full-field rounded-xl border border-emerald-200 bg-emerald-50 p-4 text-sm text-emerald-900"><strong>{selected.tasks.length} standard tasks will be created automatically</strong><p className="mt-1">Material reminders are scheduled one day before applicable tasks after a contractor is assigned.</p></div>}<label>Project name<input name="name" required/></label><label>Client<input name="client_name" required/></label><label>Location<input name="location" required/></label><input type="hidden" name="project_type" value={selected?.project_type || "Interior Fit-out"}/><input type="hidden" name="duration_days" value={selected?.duration_days || 3}/><label>Start date<input type="date" name="start_date" required/></label>{user.role !== "project_manager" && <label>Project Manager<select name="project_manager_id" required><option value="">Select PM</option>{pms.map(item => <option value={item.id} key={item.id}>{item.name}</option>)}</select></label>}<label>Supervisor<select name="supervisor_id" required><option value="">Select supervisor</option>{supervisors.map(item => <option value={item.id} key={item.id}>{item.name}{item.phone ? "" : " · phone missing"}</option>)}</select></label><label>Area<input name="area"/></label><button className="full-field">Create schedule with {selected?.tasks.length || 0} tasks</button></form></Modal>; }function TaskModal({ project, day, task, supervisors, mains, subsFor, submit, close }) { const [main, setMain] = useState(task?.assigned_contractor_id || ""); const [reminder, setReminder] = useState(task?.material_reminder || false); return <Modal title={task ? "Edit task" : `Add exceptional task · Day ${day.day_no}`} subtitle={task?.template_task_id ? "This task came from the project template and can be customized." : "Use manual tasks only for missing or additional site work."} onClose={close}><form className="modal-form two-col" onSubmit={submit}><input type="hidden" name="project_id" value={project.id}/><input type="hidden" name="day_id" value={day.id}/><label className="full-field">Task title<input name="title" defaultValue={task?.title || ""} required/></label><label>Category<input name="category" defaultValue={task?.category || "General"}/></label><label>Priority<select name="priority" defaultValue={task?.priority || "medium"}><option value="low">Low</option><option value="medium">Medium</option><option value="high">High</option></select></label><label>Supervisor<select name="assigned_supervisor_id" defaultValue={task?.assigned_supervisor_id || project.supervisor_id} required>{supervisors.map(item => <option value={item.id} key={item.id}>{item.name}{item.phone ? "" : " · phone missing"}</option>)}</select></label><label>Primary contractor<select name="assigned_contractor_id" value={main} onChange={event => setMain(event.target.value)}><option value="">No contractor</option>{mains.map(item => <option value={item.id} key={item.id}>{item.name}{item.engagement_type === "independent" ? " · Independent" : ""}</option>)}</select></label><label>Specific subcontractor<select name="assigned_subcontractor_id" defaultValue={task?.assigned_subcontractor_id || ""}><option value="">None</option>{main && subsFor(main).map(item => <option value={item.id} key={item.id}>{item.name}</option>)}</select></label><label className="full-field">Instructions<textarea name="instructions" defaultValue={task?.instructions || ""}/></label><label className="full-field">Proof requirement<input name="proof_required" defaultValue={task?.proof_required || ""} placeholder="Example: Completed-work photo and checklist"/></label><label className="full-field">Materials required<textarea name="materials_required" defaultValue={task?.materials_required || ""} placeholder="Gypsum boards, channels, screws..."/></label><label className="full-field flex items-center gap-3 rounded-xl border border-amber-200 bg-amber-50 p-4"><input className="h-5 w-5" type="checkbox" name="material_reminder" checked={reminder} onChange={event => setReminder(event.target.checked)}/><span>Schedule material reminder one day before this task</span></label><button className="full-field">{task ? "Save task and rebuild reminders" : "Add exceptional task"}</button></form></Modal>; }function DelayReportModal({ task, submit, close }) {
  const now = new Date();
  const today = new Date(now.getTime() - now.getTimezoneOffset() * 60000).toISOString().slice(0, 10);
  return <Modal title="Report task delay" subtitle="Tell the PM what stopped the work and propose a realistic recovery date." onClose={close}>
    <form className="modal-form" onSubmit={submit}>
      <section className="rounded-xl border border-blue-200 bg-blue-50 p-4 text-blue-950">
        <strong>{task.title}</strong>
        <p className="mt-2 text-sm">Current official date: {new Date(task.effective_date + "T00:00:00").toLocaleDateString("en-GB", { day:"2-digit", month:"short", year:"numeric" })}</p>
      </section>
      <label>Delay category<select name="category" defaultValue="" required><option value="" disabled>Select reason type</option><option value="material">Material unavailable</option><option value="labour">Labour or crew</option><option value="dependency">Previous work dependency</option><option value="client">Client decision</option><option value="weather">Weather</option><option value="site_condition">Site condition</option><option value="other">Other</option></select></label>
      <label>Proposed recovery date<input type="date" name="proposed_date" min={today} defaultValue={today} required/></label>
      <label>Delay reason and recovery plan<textarea name="reason" minLength="5" required placeholder="Explain what caused the delay and what is needed to restart."/></label>
      <div className="rounded-xl border border-amber-200 bg-amber-50 p-3 text-sm text-amber-900">This reports the issue to the PM. It does not change the official task date until the PM confirms a reschedule.</div>
      <button>Send delay report to PM</button>
    </form>
  </Modal>;
}

function RescheduleTaskModal({ task, submit, close }) {
  const now = new Date();
  const today = new Date(now.getTime() - now.getTimezoneOffset() * 60000).toISOString().slice(0, 10);
  const effectiveDate = task.effective_date || task.rescheduled_date || task.scheduled_date;
  const proposedDate = task.active_delay_report?.proposed_date;
  const nextEffectiveDate = new Date(`${effectiveDate}T00:00:00Z`);
  nextEffectiveDate.setUTCDate(nextEffectiveDate.getUTCDate() + 1);
  const nextDate = nextEffectiveDate.toISOString().slice(0, 10);
  const defaultDate = proposedDate && proposedDate >= today && proposedDate !== effectiveDate
    ? proposedDate
    : effectiveDate >= today ? nextDate : today;
  const [scheduledDate, setScheduledDate] = useState(defaultDate);
  const [error, setError] = useState("");
  const [saving, setSaving] = useState(false);
  const sameDate = scheduledDate === effectiveDate;

  async function confirm(event) {
    event.preventDefault();
    if (sameDate) {
      setError("Revised date must be different from the current scheduled date.");
      return;
    }
    setError("");
    setSaving(true);
    const payload = Object.fromEntries(new FormData(event.currentTarget));
    const result = await submit(payload);
    if (!result?.ok) {
      setError(result?.error || "The revised schedule could not be saved. Please try again.");
      setSaving(false);
    }
  }

  return <Modal title={task.active_delay_report ? "Confirm delayed task schedule" : "Reschedule overdue task"} subtitle="The original planned date remains preserved in audit history." onClose={close}>
    <form className="modal-form" onSubmit={confirm}>
      <section className="rounded-xl border border-amber-200 bg-amber-50 p-4 text-amber-950">
        <strong>{task.title}</strong>
        <p className="mt-2 text-sm">Original date: {new Date(task.scheduled_date + "T00:00:00").toLocaleDateString("en-GB", { day:"2-digit", month:"short", year:"numeric" })}{task.rescheduled_date ? " / Current revised date: " + new Date(task.rescheduled_date + "T00:00:00").toLocaleDateString("en-GB", { day:"2-digit", month:"short", year:"numeric" }) : ""}</p>
      </section>
      {task.active_delay_report && <section className="rounded-xl border border-blue-200 bg-blue-50 p-4 text-blue-950"><strong>Supervisor proposal</strong><p className="mt-2 text-sm">{task.active_delay_report.reason}</p><small className="mt-2 block">Category: {task.active_delay_report.category.replaceAll("_", " ")} / Proposed: {new Date(task.active_delay_report.proposed_date + "T00:00:00").toLocaleDateString("en-GB")}</small></section>}
      <label>Official revised working date<input type="date" name="scheduled_date" min={today} value={scheduledDate} onChange={event => { setScheduledDate(event.target.value); setError(""); }} aria-invalid={sameDate || Boolean(error)} aria-describedby="reschedule-date-help reschedule-error" required/><small id="reschedule-date-help" className="mt-1 block font-medium text-slate-500">Current official date: {new Date(effectiveDate + "T00:00:00").toLocaleDateString("en-GB", { day:"2-digit", month:"short", year:"numeric" })}. Choose a different working date.</small></label>
      <label>PM rescheduling reason<textarea name="reason" minLength="5" required defaultValue={task.active_delay_report?.reason || task.delay_reason || ""} placeholder="Confirm or update the reason for the official schedule change."/></label>
      {(sameDate || error) && <div id="reschedule-error" role="alert" className="rounded-xl border border-rose-300 bg-rose-50 p-3 text-sm font-bold text-rose-800">{error || "Revised date must be different from the current scheduled date."}</div>}
      <button disabled={sameDate || saving} className="disabled:cursor-not-allowed disabled:opacity-60">{saving ? "Saving revised date..." : task.active_delay_report ? "Confirm official revised date" : "Confirm revised date"}</button>
    </form>
  </Modal>;
}
function TaskDetail({ task, user, edit, reportDelay, reschedule, remove, close, canManage, onStatus, onSubmit, onReview }) {
  const [reason, setReason] = useState("");
  const isSupervisor = user.role === "supervisor";
  const isAssignedSupervisor = task.assigned_supervisor_id === user.id;
  const canSupervisorUpdate = (isSupervisor || isAssignedSupervisor) && !["submitted","approved","completed"].includes(task.status);
  const isCorrection = task.status === "rejected";
  const notificationLabel = note => note.notification_type === "material_reminder" ? "Material reminder - " + (note.scheduled_for ? new Date(note.scheduled_for).toLocaleString() : "Pending") : note.notification_type === "task_rescheduled" ? "Task rescheduled" : note.notification_type === "delay_report" ? "Delay report" : "Task assignment";
  const overdueLabel = "overdue by " + task.overdue_days + " day" + (task.overdue_days === 1 ? "" : "s");
  return <Modal title={task.title} subtitle={"Day " + task.day_no + " - " + (task.is_overdue ? overdueLabel : prettyStatus(task.status))} onClose={close}>
    <div className="grid gap-5">
      {task.is_overdue && <section className="rounded-xl border border-rose-300 bg-rose-50 p-4"><div className="flex flex-wrap items-center justify-between gap-3"><div><h4 className="font-black text-rose-950">Schedule missed by {task.overdue_days} day{task.overdue_days === 1 ? "" : "s"}</h4><p className="mt-1 text-sm text-rose-800">The task remains open and needs site action or a controlled revised date.</p></div>{canManage && <button type="button" className="bg-rose-700 text-white" onClick={reschedule}>Reschedule task</button>}</div></section>}
      {task.active_delay_report && <section className="rounded-xl border border-amber-300 bg-amber-50 p-4"><div className="flex flex-wrap items-start justify-between gap-3"><div><p className="text-[11px] font-black uppercase tracking-wider text-amber-700">Awaiting PM confirmation</p><h4 className="mt-1 font-black capitalize text-amber-950">{task.active_delay_report.category.replaceAll("_", " ")}</h4><p className="mt-2 text-sm leading-6 text-amber-900">{task.active_delay_report.reason}</p><small className="mt-2 block text-amber-700">Proposed date: {new Date(task.active_delay_report.proposed_date + "T00:00:00").toLocaleDateString("en-GB", { day:"2-digit", month:"short", year:"numeric" })} / Reported by {task.active_delay_report.created_by_name}</small></div>{canManage && <button type="button" className="bg-amber-700 text-white" onClick={reschedule}>Confirm official schedule</button>}</div></section>}
      <div className="task-v2-facts">
        <article><span>Supervisor</span><strong>{task.supervisor_name}</strong></article>
        <article><span>Assigned company</span><strong>{task.subcontractor_name || task.contractor_name || "Internal"}</strong></article>
        <article><span>Original date</span><strong>{new Date(task.scheduled_date + "T00:00:00").toLocaleDateString("en-GB", { day:"2-digit", month:"short", year:"numeric" })}</strong></article>
        <article><span>Active date</span><strong>{new Date(task.effective_date + "T00:00:00").toLocaleDateString("en-GB", { day:"2-digit", month:"short", year:"numeric" })}</strong></article>
      </div>
      {task.rescheduled_date && <section className="rounded-xl border border-amber-200 bg-amber-50 p-4"><h4 className="font-black text-amber-950">Revised schedule</h4><p className="mt-2 text-sm text-amber-900">{task.delay_reason}</p><small className="mt-2 block text-amber-700">Revised by {task.rescheduled_by_name || "SiteOps manager"} / {task.reschedule_count} change{task.reschedule_count === 1 ? "" : "s"}</small></section>}
      <section className="rounded-xl border border-slate-200 bg-slate-50 p-4"><h4 className="font-black text-slate-900">Instructions</h4><p className="mt-2 text-sm leading-6 text-slate-600">{task.instructions || "No instructions added."}</p></section>
      {task.materials_required && <section className="rounded-xl border border-amber-200 bg-amber-50 p-4"><h4 className="font-black text-amber-950">Materials required</h4><p className="mt-2 text-sm text-amber-900">{task.materials_required}</p></section>}
      {task.rejection_reason && <section className="rounded-xl border border-rose-200 bg-rose-50 p-4"><h4 className="font-black text-rose-900">PM correction requested</h4><p className="mt-2 text-sm text-rose-800">{task.rejection_reason}</p></section>}
      {task.remarks && <section><h4 className="font-black">Supervisor remarks</h4><p className="mt-2 text-sm text-slate-600">{task.remarks}</p>{task.proof_url && <a className="mt-3 inline-flex font-bold text-blue-700" href={window.location.protocol + "//" + window.location.hostname + ":8000" + task.proof_url} target="_blank" rel="noreferrer">Open submitted proof</a>}</section>}
      {canSupervisorUpdate && <section className={isCorrection ? "rounded-2xl border border-rose-300 bg-rose-50 p-5" : "rounded-2xl border border-blue-200 bg-blue-50 p-5"}><h4 className={isCorrection ? "font-black text-rose-950" : "font-black text-blue-950"}>{isCorrection ? "Correct and resubmit" : "Update site work"}</h4>{isCorrection && <p className="mt-2 text-sm leading-6 text-rose-800">This task is reopened for correction. Update the remarks and attach revised proof before sending it back to the PM.</p>}<div className="mt-3 flex flex-wrap gap-2"><button type="button" onClick={() => onStatus("in_progress")}>{task.active_delay_report ? "Restart work and withdraw delay" : "Start work"}</button>{!task.active_delay_report && <button type="button" className="secondary-button" onClick={reportDelay}>Report delay</button>}</div><form className="mt-5 grid gap-3" onSubmit={onSubmit}><label>Completion remarks<textarea name="remarks" required placeholder="Describe completed work, checks, or site observations"/></label><label>Proof photo or PDF<input type="file" name="proof" accept="image/jpeg,image/png,image/webp,application/pdf" required={Boolean(task.proof_required)}/></label><button>{isCorrection ? "Resubmit corrected work" : "Submit work for PM review"}</button></form></section>}
      {canManage && task.status === "submitted" && <section className="rounded-2xl border border-emerald-200 bg-emerald-50 p-5"><h4 className="font-black text-emerald-950">PM review</h4><p className="mt-1 text-sm text-emerald-800">Review the proof and supervisor remarks before deciding.</p><textarea className="mt-3" value={reason} onChange={event => setReason(event.target.value)} placeholder="Rejection reason (required only when rejecting)"/><div className="mt-3 flex gap-2"><button type="button" onClick={() => onReview("approve", "")}>Approve work</button><button type="button" className="danger" disabled={!reason.trim()} onClick={() => onReview("reject", reason)}>Reject with reason</button></div></section>}
      {task.delay_reports?.length > 0 && <section><h4 className="font-black">Delay report history</h4><div className="mt-3 grid gap-2">{task.delay_reports.map(item => <article key={item.id} className="rounded-xl border border-slate-200 bg-white p-3 text-sm"><div className="flex items-center justify-between gap-3"><strong className="capitalize">{item.category.replaceAll("_", " ")}</strong><Pill tone={item.status === "pending" ? "orange" : item.status === "accepted" ? "green" : "gray"}>{item.status}</Pill></div><p className="mt-2 text-slate-600">{item.reason}</p><small className="text-slate-500">Proposed {new Date(item.proposed_date + "T00:00:00").toLocaleDateString("en-GB")} / {item.created_by_name}</small></article>)}</div></section>}
      {task.reschedule_history?.length > 0 && <section><h4 className="font-black">Schedule history</h4><div className="mt-3 grid gap-2">{task.reschedule_history.map(item => <article key={item.id} className="rounded-xl border border-slate-200 bg-white p-3 text-sm"><strong>{new Date(item.previous_date + "T00:00:00").toLocaleDateString("en-GB")} to {new Date(item.new_date + "T00:00:00").toLocaleDateString("en-GB")}</strong><p className="mt-1 text-slate-600">{item.reason}</p><small className="text-slate-500">{item.created_by_name} / {new Date(item.created_at).toLocaleString("en-GB")}</small></article>)}</div></section>}
      <section><h4 className="font-black">Notification preview</h4>{task.notifications.map(note => <article className="notification-preview" key={note.id}><div><Bell/><strong>{note.recipient_name}</strong><Pill tone={["preview", "scheduled"].includes(note.status) ? "green" : "orange"}>{note.status}</Pill></div><small>{notificationLabel(note)} - {note.recipient_type} - {note.phone || "Phone missing"}</small><pre>{note.message_preview}</pre></article>)}</section>
      {canManage && <div className="task-detail-actions"><button onClick={edit}>Edit task</button><button className="danger" onClick={remove}><Trash2/> Delete</button></div>}
    </div>
  </Modal>;
}function TemplateView({ templates, open }) { return <section className="template-workspace"><header><div><p>Super Admin control</p><h3>Execution templates</h3><span>Templates generate days and starter tasks when a project is created.</span></div><button onClick={open}><Plus/> New template</button></header><div>{templates.map(template => <article key={template.id}><LayoutTemplate/><div><h4>{template.name}</h4><span>{template.project_type} · {template.duration_days} days</span></div><strong>{template.tasks.length} tasks</strong></article>)}{!templates.length && <p>No templates created yet.</p>}</div></section>; }
function TemplateModal({ submit, close }) { const [duration, setDuration] = useState(3); return <Modal title="Create execution template" subtitle="One task per line" onClose={close}><form className="modal-form" onSubmit={submit}><label>Template name<input name="name" required/></label><label>Project type<input name="project_type" required/></label><label>Duration<select name="duration_days" value={duration} onChange={event => setDuration(Number(event.target.value))}><option value="3">3 days</option><option value="7">7 days</option></select></label>{Array.from({ length: duration }, (_, index) => <label key={index}>Day {index + 1} starter tasks<textarea name={`day_${index + 1}`} placeholder="One task per line"/></label>)}<button>Create template</button></form></Modal>; }







