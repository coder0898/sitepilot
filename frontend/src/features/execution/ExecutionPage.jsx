import { useEffect, useMemo, useRef, useState } from "react";
import { Activity, AlertTriangle, BriefcaseBusiness, CalendarDays, CheckCircle2, ClipboardList, Clock3, LayoutTemplate, Plus, RefreshCw, UserRound, Users } from "lucide-react";
import { executionApi } from "../../api/executionApi";
import { Button, ConfirmModal, Pill } from "../../components/ui";
import { DayColumn, ExecutionMetric as Metric, TeamMember } from "./components/ExecutionOverview";
import { DelayReportModal, ProjectModal, ProjectSettingsModal, RescheduleTaskModal, TaskDetail, TaskModal, TemplateModal, TemplateView } from "./components/ExecutionModals";

const empty = { projects: [], days: [], tasks: [], users: [], contractors: [], categories: [], relationships: [], templates: [] };
const prettyStatus = value => String(value || "assigned").replaceAll("_", " ");

export function ExecutionPage({ user, action }) {
  const [data, setData] = useState(empty);
  const [projectId, setProjectId] = useState("");
  const [form, setForm] = useState(null);
  const [selectedTask, setSelectedTask] = useState(null);
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [view, setView] = useState("schedule");
  const [executionLoading, setExecutionLoading] = useState(false);
  const requestRef = useRef(null);
  const canManage = user.role !== "supervisor";

  async function load({ restart = false } = {}) {
    if (requestRef.current && !restart) return requestRef.current.promise;
    if (requestRef.current && restart) requestRef.current.controller.abort();

    const controller = new AbortController();
    const promise = executionApi.get({ signal: controller.signal });
    requestRef.current = { controller, promise };
    setExecutionLoading(true);
    try {
      const next = await promise;
      setData({ ...empty, ...next });
      setSelectedTask(current => current ? next.tasks.find(task => task.id === current.id) || null : null);
      setProjectId(current => next.projects.some(project => project.id === current) ? current : next.projects[0]?.id || "");
      return next;
    } finally {
      if (requestRef.current?.promise === promise) {
        requestRef.current = null;
        setExecutionLoading(false);
      }
    }
  }
  useEffect(() => {
    load().catch(error => { if (error?.name !== "AbortError") console.error(error); });
    return () => requestRef.current?.controller.abort();
  }, []);
  async function perform(fn, message) {
    let ok = false;
    const result = await action(async () => { await fn(); ok = true; }, message, { refresh: false });
    if (ok) { setForm(null); setSelectedTask(null); await load({ restart: true }); }
    return result || { ok };
  }

  const project = data.projects.find(item => item.id === projectId);
  const days = data.days.filter(item => item.project_id === projectId);
  const tasks = data.tasks.filter(item => item.project_id === projectId);
  const overdueTasks = tasks.filter(task => task.is_overdue);
  const pendingDelayTasks = tasks.filter(task => task.active_delay_report);
  const supervisors = data.users.filter(item => item.role === "supervisor");
  const pms = data.users.filter(item => item.role === "project_manager");
  const mains = data.contractors.filter(item => item.engagement_type === "main" && item.status === "active" && item.migration_status === "ready");
  const subsFor = id => data.contractors.filter(item => item.engagement_type === "sub_vendor" && item.parent_vendor_id === id && item.status === "active" && item.migration_status === "ready");
  const progress = tasks.length ? Math.round(tasks.filter(task => ["approved", "completed"].includes(task.status)).length / tasks.length * 100) : 0;
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
    payload.category_id = payload.category_id || null;
    payload.subcategory_id = payload.subcategory_id || null;
    payload.assigned_contractor_id = payload.assigned_contractor_id || null;
    payload.assigned_subcontractor_id = payload.assigned_subcontractor_id || null;
    payload.material_reminder = payload.material_reminder === "on";
    payload.reminder_lead_days = 1;
    await perform(() => selectedTask ? executionApi.updateTask(selectedTask.id, payload) : executionApi.createTask(payload), selectedTask ? "Task updated" : "Task created");
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
    <div className="exec-dashboard grid min-w-0 max-w-full gap-4 text-slate-900">
      <section className="exec-welcome flex items-center justify-between gap-5 max-[720px]:grid [&>div:first-child]:min-w-0 [&>div:first-child>p]:m-0 [&>div:first-child>p]:font-serif [&>div:first-child>p]:text-2xl [&>div:first-child>p]:font-bold [&>div:first-child>small]:mt-1 [&>div:first-child>small]:block [&>div:first-child>small]:font-bold [&>div:first-child>small]:text-slate-500">
        <div><p>Good morning, {user.name.split(" ")[0]}!</p><small>{project?.name || "Select or create an execution project"}{project?.template_name ? ` · ${project.template_name}` : ""}</small></div>
        <div className="exec-welcome-actions flex items-center gap-2 max-[720px]:grid max-[720px]:grid-cols-1 [&>label]:flex [&>label]:min-h-11 [&>label]:min-w-[230px] [&>label]:items-center [&>label]:gap-2 [&>label]:rounded-xl [&>label]:border [&>label]:border-slate-200 [&>label]:bg-white [&>label]:px-3 max-[720px]:[&>label]:min-w-0 [&_select]:border-0 [&_select]:bg-transparent [&_select]:p-0 [&_select]:outline-none [&>button]:flex [&>button]:min-h-11 [&>button]:items-center [&>button]:justify-center [&>button]:gap-2 [&>button]:inline-flex [&>button]:items-center [&>button]:justify-center [&>button]:gap-2 [&>button]:rounded-xl [&>button]:bg-blue-700 [&>button]:px-4 [&>button]:font-black [&>button]:text-white">
          <label><BriefcaseBusiness size={16}/><select value={projectId} onChange={event => setProjectId(event.target.value)}><option value="">Select project</option>{data.projects.map(item => <option value={item.id} key={item.id}>{item.name}</option>)}</select></label>
          {user.role === "super_admin" && <button className="exec-icon-button !size-11 !bg-violet-100 !p-0 !text-violet-700" onClick={() => setView(view === "templates" ? "schedule" : "templates")} aria-label="Execution templates"><LayoutTemplate/></button>}
          {canManage && project && <button className="secondary-button border border-slate-200 bg-white text-slate-700 shadow-sm hover:bg-slate-50" onClick={() => setForm("project-settings")}>Edit project</button>}{canManage && <button className="flex" onClick={() => setForm("project")}><Plus/> New project</button>}
        </div>
      </section>

      {view === "templates" && user.role === "super_admin" ? <TemplateView templates={data.templates} open={() => setForm("template")}/> : <>
        <section className="exec-metrics grid grid-cols-5 gap-3 max-[1180px]:grid-cols-3 max-[720px]:grid-cols-2 max-[420px]:grid-cols-1">
          <Metric icon={<ClipboardList/>} label="Total tasks" value={tasks.length} helper={`${tasks.filter(task => task.status === "completed").length} completed`} tone="blue"/>
          <Metric icon={<Clock3/>} label="Assigned tasks" value={statusCounts.assigned || 0} helper="Ready to start" tone="orange"/>
          <Metric icon={<AlertTriangle/>} label="Overdue tasks" value={overdueTasks.length} helper={overdueTasks.length ? "Action required" : "Schedule on track"} tone="red"/>
          <Metric icon={<Activity/>} label="Project progress" value={`${progress}%`} helper={`${project?.duration_days || 3}-day schedule`} tone="green" progress={progress}/>
          <Metric icon={<Users/>} label="Assigned companies" value={assignedCompanies} helper="Contractors on tasks" tone="violet"/>
        </section>

        {project ? <>
          {overdueTasks.length > 0 && <section className="min-w-0 max-w-full overflow-hidden rounded-[18px] border border-rose-300 bg-gradient-to-r from-rose-50 to-amber-50 p-4 shadow-[0_12px_30px_rgba(190,24,93,0.08)]">
            <div className="flex flex-wrap items-start justify-between gap-3">
              <div className="min-w-0"><p className="m-0 text-[11px] font-black uppercase tracking-[0.14em] text-rose-700">Attention required</p><h3 className="mt-1 font-serif text-xl text-rose-950">{overdueTasks.length} overdue {overdueTasks.length === 1 ? "task" : "tasks"}</h3><p className="mt-1 text-sm text-rose-800">These tasks passed their active working date and are not submitted or approved.</p></div>
              <Pill tone="red">PM action</Pill>
            </div>
            <div className="mt-4 grid gap-2 md:grid-cols-2 xl:grid-cols-3">{overdueTasks.map(task => <button type="button" key={task.id} onClick={() => setSelectedTask(task)} className="flex min-w-0 items-center justify-between gap-3 rounded-xl border border-rose-200 bg-white px-4 py-3 text-left text-slate-900 shadow-none transition hover:-translate-y-0.5 hover:border-rose-400 hover:bg-white">
              <span className="min-w-0"><strong className="block truncate text-sm">{task.title}</strong><small className="mt-1 block text-xs text-slate-500">Day {task.day_no} · planned {new Date(task.effective_date + "T00:00:00").toLocaleDateString("en-GB", { day:"2-digit", month:"short" })}</small></span>
              <span className="shrink-0 rounded-full bg-rose-100 px-3 py-1 text-xs font-black text-rose-700">{task.overdue_days}d overdue</span>
            </button>)}</div>
          </section>}
          {pendingDelayTasks.length > 0 && <section className="min-w-0 max-w-full overflow-hidden rounded-[18px] border border-amber-300 bg-amber-50 p-4 shadow-[0_12px_30px_rgba(180,83,9,0.08)]">
            <div className="flex flex-wrap items-start justify-between gap-3">
              <div className="min-w-0"><p className="m-0 text-[11px] font-black uppercase tracking-[0.14em] text-amber-700">Delay reports</p><h3 className="mt-1 font-serif text-xl text-amber-950">{pendingDelayTasks.length} awaiting PM confirmation</h3><p className="mt-1 text-sm text-amber-800">Supervisor proposals do not change the official task date until the PM confirms a reschedule.</p></div>
              <Pill tone="orange">Review required</Pill>
            </div>
            <div className="mt-4 grid gap-2 md:grid-cols-2 xl:grid-cols-3">{pendingDelayTasks.map(task => <button type="button" key={task.id} onClick={() => setSelectedTask(task)} className="flex min-w-0 items-center justify-between gap-3 rounded-xl border border-amber-200 bg-white px-4 py-3 text-left text-slate-900 shadow-none transition hover:-translate-y-0.5 hover:border-amber-400">
              <span className="min-w-0"><strong className="block truncate text-sm">{task.title}</strong><small className="mt-1 block text-xs text-slate-500">{task.active_delay_report.category.replaceAll("_", " ")} · proposed {new Date(task.active_delay_report.proposed_date + "T00:00:00").toLocaleDateString("en-GB", { day:"2-digit", month:"short" })}</small></span>
              <span className="shrink-0 rounded-full bg-amber-100 px-3 py-1 text-xs font-black text-amber-800">Pending</span>
            </button>)}</div>
          </section>}
          <div className="exec-primary-grid grid min-w-0 grid-cols-1 items-start gap-4 max-[1180px]:grid-cols-1">
            <section className="exec-calendar-card min-w-0 overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-[0_10px_30px_rgba(26,47,78,0.06)] [&>header]:flex [&>header]:items-center [&>header]:justify-between [&>header]:gap-3 [&>header]:border-b [&>header]:border-slate-200 [&>header]:px-5 [&>header]:py-4 [&_h3]:m-0 [&_h3]:font-serif [&_h3]:text-lg [&>footer]:flex [&>footer]:justify-center [&>footer]:gap-5 [&>footer]:border-t [&>footer]:border-slate-200 [&>footer]:p-3 [&>footer]:text-xs [&>footer]:text-slate-500">
              <header><div><h3>3-Day Execution Calendar</h3><span>{project.client_name} · {project.location}</span></div><Pill tone="blue">{project.status}</Pill></header>
              <div className="exec-day-grid grid grid-cols-3 p-3 max-[720px]:grid-cols-1 max-[720px]:gap-3">{days.map(day => <DayColumn key={day.id} day={day} tasks={tasks.filter(task => task.day_id === day.id)} canManage={canManage} add={() => openTask(day)} select={setSelectedTask}/>)}</div>
              <footer><span className="inline-flex items-center before:mr-1 before:size-2 before:rounded-full before:bg-blue-500">Assigned</span><span className="inline-flex items-center before:mr-1 before:size-2 before:rounded-full before:bg-emerald-500">Completed</span><span className="inline-flex items-center before:mr-1 before:size-2 before:rounded-full before:bg-rose-500">High priority</span></footer>
            </section>
          </div>

          <section className="exec-secondary-grid grid grid-cols-[1fr_1.3fr] gap-4 max-[1180px]:grid-cols-1">
            <article className="exec-status-card min-w-0 overflow-hidden rounded-2xl border border-slate-200 bg-white p-5 shadow-[0_10px_30px_rgba(26,47,78,0.06)] [&>header]:flex [&>header]:justify-between [&_h3]:m-0 [&_h3]:font-serif [&_h3]:text-lg"><header><h3>Task Status Overview</h3><strong>{tasks.length}</strong></header><div className="status-ring relative float-left m-1 mr-6 mt-5 grid size-[120px] place-items-center rounded-full bg-[conic-gradient(#23ba81_var(--progress),#e5ebf2_0)] after:absolute after:inset-[18px] after:rounded-full after:bg-white [&>span]:z-10 [&>span]:grid [&>span]:text-center [&>span]:text-xl [&>span]:font-black [&_small]:text-[10px] [&_small]:text-slate-500" style={{ "--progress": `${progress * 3.6}deg` }}><span>{progress}%<small>Complete</small></span></div><div className="status-list mt-5 grid gap-2 [&>p]:m-0 [&>p]:grid [&>p]:grid-cols-[auto_1fr_auto] [&>p]:items-center [&>p]:gap-2 [&>p]:text-xs [&>p]:capitalize [&>p]:text-slate-600">{Object.entries(statusCounts).map(([statusName, count]) => <p key={statusName}><span className={`size-2 rounded-full ${["completed","approved"].includes(statusName) ? "bg-emerald-500" : statusName === "assigned" ? "bg-amber-500" : "bg-blue-500"}`}></span>{prettyStatus(statusName)}<strong>{count}</strong></p>)}{!tasks.length && <p>No tasks yet</p>}</div></article>
            <article className="exec-team-card min-w-0 rounded-2xl border border-slate-200 bg-white p-5 shadow-[0_10px_30px_rgba(26,47,78,0.06)] [&>header]:flex [&>header]:justify-between [&>div]:mt-4 [&>div]:grid [&>div]:grid-cols-2 [&>div]:gap-3 max-[720px]:[&>div]:grid-cols-1 [&_h3]:m-0 [&_h3]:font-serif [&_h3]:text-lg [&_article]:grid [&_article]:grid-cols-[auto_1fr] [&_article]:items-center [&_article]:gap-3 [&_article]:rounded-xl [&_article]:bg-slate-50 [&_article]:p-4 [&_article>span]:grid [&_article>span]:size-10 [&_article>span]:place-items-center [&_article>span]:rounded-full [&_article>span]:bg-blue-50 [&_article>span]:text-blue-700 [&_article>div]:grid [&_article_strong]:text-sm [&_article_small]:text-xs [&_article_small]:text-slate-500 [&_article_p]:m-0 [&_article_p]:text-xs [&_article_p]:text-slate-500"><header><h3>Project Team</h3><span>Current assignments</span></header><div><TeamMember icon={<UserRound/>} name={pm?.name || user.name} role="Project Manager" phone={pm?.phone}/><TeamMember icon={<Users/>} name={supervisor?.name || "Not assigned"} role="Site Supervisor" phone={supervisor?.phone}/></div></article>
          </section>


          {canManage && <section className="exec-quick-actions rounded-2xl border border-slate-200 bg-white p-5 shadow-[0_10px_30px_rgba(26,47,78,0.06)] [&>h3]:m-0 [&>h3]:font-serif [&>h3]:text-lg [&>div]:mt-3 [&>div]:flex [&>div]:gap-3 max-[720px]:[&>div]:grid [&_button]:flex [&_button]:items-center [&_button]:justify-center [&_button]:gap-2 [&_button]:rounded-xl [&_button]:border [&_button]:border-slate-200 [&_button]:bg-white [&_button]:px-4 [&_button]:py-3 [&_button]:font-bold [&_button]:text-slate-700"><h3>Quick Actions</h3><div><button onClick={() => openTask(days[0])} disabled={!days[0]}><Plus/><span>Add task</span></button><button onClick={() => setForm("project")}><CalendarDays/><span>New project</span></button>{user.role === "super_admin" && <button onClick={() => setView("templates")}><LayoutTemplate/><span>Templates</span></button>}</div></section>}
        </> : <section className="empty-execution grid min-h-[360px] place-items-center content-center gap-3 rounded-2xl border border-dashed border-slate-300 bg-white/70 p-8 text-center [&>svg]:size-12 [&>svg]:text-violet-600 [&>h3]:m-0 [&>h3]:text-xl [&>p]:m-0 [&>p]:text-slate-500 [&>button]:inline-flex [&>button]:items-center [&>button]:justify-center [&>button]:gap-2 [&>button]:rounded-xl [&>button]:bg-blue-700 [&>button]:px-5 [&>button]:py-3 [&>button]:font-black [&>button]:text-white"><CalendarDays/><h3>Create your first three-day project</h3><p>The scheduler will generate Day 1, Day 2 and Day 3 automatically.</p>{canManage && <button onClick={() => setForm("project")}><Plus/> Create project</button>}</section>}
      </>}

      {form === "project-settings" && project && <ProjectSettingsModal project={project} pms={pms} supervisors={supervisors} submit={saveProject} remove={deleteProject} close={() => setForm(null)}/>}
      {form === "project" && <ProjectModal user={user} pms={pms} supervisors={supervisors} templates={data.templates} submit={createProject} close={() => setForm(null)}/>}
      {form?.type === "task" && <TaskModal project={project} day={form.day} task={null} supervisors={supervisors} mains={mains} subsFor={subsFor} categories={data.categories} submit={saveTask} close={() => setForm(null)}/>}
      {selectedTask && form?.type !== "edit" && !["reschedule","delay-report"].includes(form) && <TaskDetail task={selectedTask} user={user} categories={data.categories} edit={() => setForm({ type: "edit", day: days.find(day => day.id === selectedTask.day_id) })} reportDelay={() => setForm("delay-report")} reschedule={() => setForm("reschedule")} remove={() => setConfirmDelete(true)} close={() => setSelectedTask(null)} canManage={canManage} onStatus={changeStatus} onSubmit={submitWork} onReview={reviewTask}/>}
      {form?.type === "edit" && selectedTask && <TaskModal project={project} day={form.day} task={selectedTask} supervisors={supervisors} mains={mains} subsFor={subsFor} categories={data.categories} submit={saveTask} close={() => setForm(null)}/>}
      {form === "delay-report" && selectedTask && <DelayReportModal task={selectedTask} submit={reportDelay} close={() => setForm(null)}/>}
      {form === "reschedule" && selectedTask && <RescheduleTaskModal task={selectedTask} submit={rescheduleTask} close={() => setForm(null)}/>}
      {form === "template" && <TemplateModal submit={createTemplate} close={() => setForm(null)}/>}
      {confirmDelete && <ConfirmModal title="Delete task?" message="This permanently removes the task and its recorded workflow history." confirmLabel="Delete task" onClose={() => setConfirmDelete(false)} onConfirm={remove}/>}
    </div>
  );
}

