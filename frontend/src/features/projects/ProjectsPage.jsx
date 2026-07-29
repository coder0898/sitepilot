import { BriefcaseBusiness, CalendarDays, ChevronRight, CircleAlert, FolderKanban, MapPin, Plus, Search, ShieldCheck, UsersRound } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import { projectsApi } from "../../api/projectsApi";
import { Button, EmptyState, LoadingSpinner, Pill, Select } from "../../components/ui";
import { ProjectDetailModal } from "./components/ProjectDetailModal";
import { ProjectFormModal } from "./components/ProjectFormModal";

const statusTone = { draft: "gray", active: "green", on_hold: "orange", completed: "blue", archived: "gray" };
const statusLabel = value => value.replace("_", " ");
const teamMember = (project, role) => project.memberships.find(item => item.project_role === role);

function SetupProgress({ project }) {
  const ready = [project.setup.has_project_manager, project.setup.has_site_supervisor, project.setup.has_template, project.setup.has_target_handover_date].filter(Boolean).length;
  return <div><div className="flex items-center justify-between text-[11px] font-black text-slate-500"><span>Setup</span><span>{ready}/4</span></div><div className="mt-2 h-1.5 overflow-hidden rounded-full bg-slate-100"><span className="block h-full rounded-full bg-blue-600 transition-all" style={{ width: `${ready * 25}%` }}/></div></div>;
}

function ProjectCard({ project, onOpen }) {
  const pm = teamMember(project, "project_manager");
  const supervisor = teamMember(project, "site_supervisor");
  return <button onClick={() => onOpen(project.id)} className="group grid w-full gap-4 rounded-2xl border border-slate-200 bg-white p-4 text-left shadow-[0_10px_32px_rgba(15,23,42,.05)] transition hover:-translate-y-0.5 hover:border-blue-200 hover:shadow-[0_18px_45px_rgba(37,99,235,.1)] sm:p-5">
    <div className="flex items-start justify-between gap-3"><div className="min-w-0"><span className="text-[10px] font-black uppercase tracking-[.16em] text-blue-700">{project.code}</span><h3 className="mt-1 truncate text-base font-black text-slate-950">{project.name}</h3><p className="mt-1 truncate text-xs text-slate-500">{project.client_name}</p></div><Pill tone={statusTone[project.status]}>{statusLabel(project.status)}</Pill></div>
    <div className="flex items-start gap-2 text-xs text-slate-500"><MapPin size={15} className="mt-0.5 shrink-0"/><span className="line-clamp-2 leading-5">{project.site_address}</span></div>
    <div className="grid grid-cols-2 gap-2"><div className="rounded-xl bg-slate-50 p-3"><span className="block text-[10px] font-black uppercase tracking-wider text-slate-400">Project Manager</span><strong className="mt-1 block truncate text-xs text-slate-700">{pm?.name || "Unassigned"}</strong></div><div className="rounded-xl bg-slate-50 p-3"><span className="block text-[10px] font-black uppercase tracking-wider text-slate-400">Supervisor</span><strong className="mt-1 block truncate text-xs text-slate-700">{supervisor?.name || "Unassigned"}</strong></div></div>
    <SetupProgress project={project}/><span className="inline-flex items-center justify-end gap-1 text-xs font-black text-blue-700">Open project <ChevronRight size={15} className="transition group-hover:translate-x-0.5"/></span>
  </button>;
}

export function ProjectsPage({ user, action }) {
  const [projects, setProjects] = useState([]);
  const [references, setReferences] = useState({ project_managers: [], supervisors: [], internal_employees: [] });
  const [publishedTemplates, setPublishedTemplates] = useState([]);
  const [templatesLoading, setTemplatesLoading] = useState(false);
  const [templatesError, setTemplatesError] = useState("");
  const [search, setSearch] = useState("");
  const [status, setStatus] = useState("");
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [formProject, setFormProject] = useState(undefined);
  const [detailId, setDetailId] = useState(null);
  const [formError, setFormError] = useState("");
  const initialLoadStarted = useRef(false);

  async function loadPublishedTemplates() {
    if (!["admin", "super_admin"].includes(user.role)) {
      setPublishedTemplates([]);
      return;
    }
    setTemplatesLoading(true);
    setTemplatesError("");
    try {
      const response = await projectsApi.publishedTemplates();
      const items = Array.isArray(response) ? response : (response?.items || []);
      setPublishedTemplates(items.filter(item => item.status === "published"));
    } catch (error) {
      setPublishedTemplates([]);
      setTemplatesError(error?.message || "Unable to load published templates. Refresh and try again.");
    } finally {
      setTemplatesLoading(false);
    }
  }

  async function load() {
    setLoading(true);
    try {
      const [items, refs] = await Promise.all([projectsApi.list(), projectsApi.references()]);
      setProjects(items);
      setReferences({
        ...refs,
        project_managers: (refs.project_managers || []).filter(item => item.availability !== "unavailable"),
        supervisors: (refs.supervisors || []).filter(item => item.availability !== "unavailable"),
      });
      await loadPublishedTemplates();
    }
    catch (error) { await action(() => Promise.reject(error), "", { refresh: false }); }
    finally { setLoading(false); }
  }
  useEffect(() => {
    if (initialLoadStarted.current) return;
    initialLoadStarted.current = true;
    load();
  }, []);
  const filtered = useMemo(() => projects.filter(project => {
    const term = search.trim().toLowerCase();
    return (!status || project.status === status) && (!term || [project.code, project.name, project.client_name, project.site_address].some(value => value.toLowerCase().includes(term)));
  }), [projects, search, status]);
  const counts = useMemo(() => ({ total: projects.length, active: projects.filter(item => item.status === "active").length, drafts: projects.filter(item => item.status === "draft").length, attention: projects.filter(item => !item.setup.activation_ready && item.status === "draft").length }), [projects]);

  async function saveProject(payload) {
    if (saving) return;
    setSaving(true);
    setFormError("");
    const editing = Boolean(formProject);
    try {
      if (editing) {
        await projectsApi.update(formProject.id, payload);
        setFormProject(undefined);
        await load();
        setDetailId(formProject.id);
      } else {
        const created = await projectsApi.create(payload);
        const createdProjectId = created.project_id || created.id;
        setFormProject(undefined);
        await load();
        if (createdProjectId) setDetailId(createdProjectId);
      }
    } catch (error) {
      const detail = error?.details?.detail;
      const message = Array.isArray(detail)
        ? detail.map(item => {
            const location = Array.isArray(item.loc) ? item.loc.filter(part => part !== "body").join(".") : "";
            return `${location ? `${location}: ` : ""}${item.msg || "Invalid value"}`;
          }).join(" ")
        : typeof detail === "string" ? detail
        : detail && typeof detail === "object" ? JSON.stringify(detail)
        : error.message || "Unable to save project.";
      setFormError(message);
    } finally {
      setSaving(false);
    }
  }

  return <section className="grid gap-5">
    <header className="flex flex-col gap-4 rounded-[24px] border border-slate-200/80 bg-white p-5 shadow-[0_16px_50px_rgba(15,23,42,.06)] sm:p-6 lg:flex-row lg:items-end lg:justify-between"><div><div className="flex items-center gap-2 text-[10px] font-black uppercase tracking-[.2em] text-blue-700"><BriefcaseBusiness size={15}/> Project portfolio</div><h2 className="mt-2 text-2xl font-black tracking-[-.035em] text-slate-950 sm:text-3xl">Projects under control</h2><p className="mt-2 max-w-2xl text-sm leading-6 text-slate-500">Create accountable project records first. Templates, schedules and field execution attach only after the draft setup is complete.</p></div>{["admin", "super_admin"].includes(user.role) && <Button size="lg" onClick={() => { setFormError(""); setFormProject(null); }}><Plus size={18}/> New project</Button>}</header>

    <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">{[["All projects", counts.total, FolderKanban, "blue"], ["Active", counts.active, ShieldCheck, "green"], ["Draft setup", counts.drafts, CalendarDays, "gray"], ["Needs attention", counts.attention, CircleAlert, "orange"]].map(([label, value, Icon, tone]) => <article key={label} className="rounded-2xl border border-slate-200 bg-white p-4"><span className={`grid size-9 place-items-center rounded-xl ${tone === "green" ? "bg-emerald-50 text-emerald-700" : tone === "orange" ? "bg-amber-50 text-amber-700" : tone === "gray" ? "bg-slate-100 text-slate-600" : "bg-blue-50 text-blue-700"}`}><Icon size={17}/></span><strong className="mt-4 block text-2xl font-black tracking-tight text-slate-950">{value}</strong><span className="mt-1 block text-xs font-bold text-slate-500">{label}</span></article>)}</div>

    <div className="flex flex-col gap-3 rounded-2xl border border-slate-200 bg-white p-3 sm:flex-row"><label className="relative min-w-0 flex-1"><Search className="pointer-events-none absolute left-3.5 top-1/2 -translate-y-1/2 text-slate-400" size={18}/><input value={search} onChange={event => setSearch(event.target.value)} className="min-h-12 w-full rounded-xl border border-slate-200 bg-white pl-11 pr-4 text-sm outline-none transition placeholder:text-slate-400 focus:border-blue-600 focus:ring-4 focus:ring-blue-600/10" placeholder="Search project, code, client or site"/></label><Select value={status} onChange={event => setStatus(event.target.value)} className="sm:max-w-52"><option value="">All statuses</option><option value="draft">Draft</option><option value="active">Active</option><option value="on_hold">On hold</option><option value="completed">Completed</option><option value="archived">Archived</option></Select></div>

    {loading ? <div className="rounded-2xl border border-slate-200 bg-white p-8"><LoadingSpinner label="Loading project portfolio..."/></div> : filtered.length ? <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">{filtered.map(project => <ProjectCard key={project.id} project={project} onOpen={setDetailId}/>)}</div> : <EmptyState icon={<FolderKanban size={21}/>} title={projects.length ? "No projects match these filters" : "Create the first controlled project"} description={projects.length ? "Try another search or status." : ["admin", "super_admin"].includes(user.role) ? "Start with a draft, assign accountability, then attach the approved 45-day template." : "Projects will appear when you receive an active project membership."} action={!projects.length && formProject === undefined && ["admin", "super_admin"].includes(user.role) ? <Button onClick={() => { setFormError(""); setFormProject(null); }}><Plus size={17}/> Create draft</Button> : null}/>} 

    {formProject !== undefined && <ProjectFormModal project={formProject} references={references} templates={publishedTemplates} templatesLoading={templatesLoading} templatesError={templatesError} apiError={formError} onClose={() => { if (!saving) setFormProject(undefined); }} onSubmit={saveProject} saving={saving}/>} 
    {detailId && <ProjectDetailModal projectId={detailId} references={references} templates={publishedTemplates} user={user} onClose={() => setDetailId(null)} onEdit={project => { setDetailId(null); setFormProject(project); }} onChanged={load} onDeleted={() => { setDetailId(null); load(); }}/>} 
  </section>;
}
