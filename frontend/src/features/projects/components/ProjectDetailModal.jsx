import { Activity, CalendarDays, Check, CircleAlert, Clock3, Layers3, MapPin, Pencil, RotateCcw, ShieldCheck, UserPlus, UsersRound } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { Button, DetailGrid, EmptyState, Field, Input, Modal, Pill, Select } from "../../../components/ui";
import { projectsApi } from "../../../api/projectsApi";
import { ProjectTemplateReview } from "./ProjectTemplateReview";
import { ProjectExternalGates } from "./ProjectExternalGates";
import { ProjectDependencies } from "./ProjectDependencies";
import { ProjectTeamReplaceModal } from "./ProjectTeamReplaceModal";
import { PendingRoleChangesPanel } from "./PendingRoleChangesPanel";

const statusTone = { draft: "gray", active: "green", on_hold: "orange", completed: "blue", archived: "gray" };
const roleLabel = { project_manager: "Project Manager", site_supervisor: "Site Supervisor", internal_employee: "Internal Employee" };
const actionLabel = value => value.toLowerCase().replaceAll("_", " ").replace(/(^|\s)\S/g, match => match.toUpperCase());

function Overview({ project }) {
  const readiness = [
    ["Project Manager", project.setup.has_project_manager], ["Site Supervisor", project.setup.has_site_supervisor],
    ["45-day template", project.setup.has_template], ["Handover date", project.setup.has_target_handover_date],
  ];
  return <div className="grid gap-4">
    <section className="rounded-2xl border border-slate-200 bg-white p-5">
      <div className="flex items-start gap-3"><span className="grid size-10 shrink-0 place-items-center rounded-xl bg-blue-50 text-blue-700"><MapPin size={18}/></span><div><h3 className="font-black text-slate-950">Site brief</h3><p className="mt-1 whitespace-pre-wrap text-sm leading-6 text-slate-600">{project.site_address}</p>{project.description && <p className="mt-3 border-t border-slate-100 pt-3 text-sm leading-6 text-slate-500">{project.description}</p>}</div></div>
    </section>
    <DetailGrid items={[
      { label: "Start date", value: new Date(`${project.start_date}T00:00:00`).toLocaleDateString("en-GB", { day: "2-digit", month: "short", year: "numeric" }) },
      { label: "Target handover", value: project.target_handover_date ? new Date(`${project.target_handover_date}T00:00:00`).toLocaleDateString("en-GB", { day: "2-digit", month: "short", year: "numeric" }) : "Calculated after template selection" },
      { label: "Client", value: project.client_name }, { label: "Template", value: project.setup.has_template ? "Approved version attached" : "Not attached" },
    ]}/>
    <section className="rounded-2xl border border-slate-200 bg-slate-50 p-4 sm:p-5"><div className="flex items-center justify-between gap-3"><div><h3 className="font-black text-slate-950">Activation checklist</h3><p className="mt-1 text-xs text-slate-500">Every accountable setup item is required before work can begin.</p></div><Pill tone={project.setup.activation_ready ? "green" : "orange"}>{project.setup.activation_ready ? "Ready" : "Setup required"}</Pill></div><div className="mt-4 grid gap-2 sm:grid-cols-2">{readiness.map(([label, ready]) => <div key={label} className={`flex items-center gap-2 rounded-xl border px-3 py-3 text-sm font-bold ${ready ? "border-emerald-200 bg-emerald-50 text-emerald-800" : "border-slate-200 bg-white text-slate-500"}`}>{ready ? <Check size={16}/> : <Clock3 size={16}/>} {label}</div>)}</div></section>
  </div>;
}

function Team({ project, references, user, onChanged }) {
  const [replaceRole, setReplaceRole] = useState(null);
  const pm = project.memberships?.find(m => m.project_role === "project_manager");
  const supervisor = project.memberships?.find(m => m.project_role === "site_supervisor");
  // U6: the two-step request/approval flow (BR-007) specifically governs
  // replacement on ACTIVE projects - gating "Change" to draft-only left
  // this unit's flow with no UI entry point once a project goes active.
  const canRequestChange = ["draft", "active"].includes(project.status) && user.role === "admin";

  return <div className="grid gap-4">
    <section className="grid gap-3 sm:grid-cols-3">
      {[
        ["Creator", project.creator?.name || project.created_by_name || "—"],
        ["Project Manager", pm?.name || "Not assigned"],
        ["Supervisor", supervisor?.name || "Not assigned"]
      ].map(([label,value]) => <article key={label} className="rounded-2xl border bg-white p-4">
        <p className="text-xs text-slate-500">{label}</p>
        <h4 className="mt-2 font-black">{value}</h4>
        {(label==="Project Manager" || label==="Supervisor") && canRequestChange &&
          <Button className="mt-3" onClick={()=>setReplaceRole(label==="Project Manager"?"project_manager":"site_supervisor")}>Change</Button>}
      </article>)}
    </section>

    <section className="rounded-2xl border bg-white p-4">
      <h3 className="font-black">Memberships</h3>
      <div className="mt-3 grid gap-2">{(project.memberships || []).map(m=>
        <div key={m.id} className="rounded-xl border p-3">{m.name} - {roleLabel[m.project_role]}</div>
      )}</div>
    </section>

    <PendingRoleChangesPanel projectId={project.id} user={user} onChanged={onChanged}/>

    {replaceRole && <ProjectTeamReplaceModal project={project} role={replaceRole} references={references} onClose={()=>setReplaceRole(null)} onChanged={onChanged}/>}
  </div>;
}

function Lifecycle({ project, user, onChanged, onDeleted }) {
  const transitions = user.role === "admin"
    ? { draft: ["active", "archived"], active: ["on_hold", "completed", "archived"], on_hold: ["active", "completed", "archived"], completed: ["archived"], archived: [] }[project.status]
    : user.role === "project_manager"
      ? { active: ["on_hold", "completed"], on_hold: ["completed"] }[project.status] || []
      : [];
  const canDelete = user.role === "admin" && project.status === "draft" && !project.template_version_id && project.memberships.length === 0;
  const [target, setTarget] = useState(transitions[0] || "");
  const [reason, setReason] = useState("");
  const [confirmation, setConfirmation] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  if (!transitions.length && !canDelete) return null;
  async function changeStatus(event) {
    event.preventDefault(); setBusy(true); setError("");
    try { await projectsApi.setStatus(project.id, target, reason); setReason(""); await onChanged(); }
    catch (caught) { setError(caught.message); }
    finally { setBusy(false); }
  }
  async function removeDraft() {
    setBusy(true); setError("");
    try { await projectsApi.remove(project.id, { confirmation, reason }); await onDeleted(); }
    catch (caught) { setError(caught.message); setBusy(false); }
  }
  const activationBlocked = target === "active" && project.status === "draft" && !project.setup.activation_ready;
  return <section className="rounded-2xl border border-slate-200 bg-white p-4 sm:p-5">
    <div className="flex items-center gap-3"><span className="grid size-10 place-items-center rounded-xl bg-slate-100 text-slate-700"><ShieldCheck size={18}/></span><div><h3 className="font-black text-slate-950">Project lifecycle</h3><p className="text-xs text-slate-500">Every transition requires a reason and is retained in activity.</p></div></div>
    {error && <div className="mt-4 rounded-xl border border-rose-200 bg-rose-50 p-3 text-sm font-bold text-rose-700">{error}</div>}
    {transitions.length > 0 && <form onSubmit={changeStatus} className="mt-4 grid gap-3 sm:grid-cols-[180px_minmax(0,1fr)_auto] sm:items-end"><Field label="Move project to"><Select value={target} onChange={event => setTarget(event.target.value)}>{transitions.map(value => <option key={value} value={value}>{actionLabel(value)}</option>)}</Select></Field><Field label="Reason"><Input value={reason} onChange={event => setReason(event.target.value)} minLength={4} required placeholder="Operational reason for this change"/></Field><Button type="submit" loading={busy} disabled={activationBlocked}>Confirm</Button>{activationBlocked && <p className="text-xs font-bold text-amber-700 sm:col-span-3">Complete all four activation checklist items first. Template selection will become available in the next module.</p>}</form>}
    {canDelete && <div className="mt-5 border-t border-slate-100 pt-5"><h4 className="text-sm font-black text-rose-700">Delete unused draft</h4><p className="mt-1 text-xs leading-5 text-slate-500">Only a draft with no team and no template can be permanently deleted. Type <strong>{project.code}</strong> and provide the reason.</p><div className="mt-3 grid gap-3 sm:grid-cols-[180px_minmax(0,1fr)_auto] sm:items-end"><Field label="Project code"><Input value={confirmation} onChange={event => setConfirmation(event.target.value)} placeholder={project.code}/></Field><Field label="Deletion reason"><Input value={reason} onChange={event => setReason(event.target.value)} minLength={4} placeholder="Why is this draft being removed?"/></Field><Button variant="danger" disabled={confirmation !== project.code || reason.length < 4} loading={busy} onClick={removeDraft}>Delete draft</Button></div></div>}
  </section>;
}

function TemplateReview({ project, activity, templates, user, onGenerated, showReview = true }) {
  const generationEvent = activity.find(event => event.action === "PROJECT_TASKS_GENERATED");
  const existingCount = generationEvent?.after?.generated_task_count || 0;
  const selectedTemplate = templates.find(item => item.version_id === project.template_version_id);
  const [confirmed, setConfirmed] = useState(false);
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState(existingCount ? { generated_task_count: existingCount, no_op: true } : null);
  const [error, setError] = useState("");
  const canGenerate = ["admin", "super_admin"].includes(user.role) && project.status === "draft" && Boolean(project.template_version_id);

  async function generate() {
    if (busy || !confirmed || !canGenerate) return;
    setBusy(true);
    setError("");
    try {
      const response = await projectsApi.generateTasks(project.id);
      setResult(response);
      setConfirmed(false);
      await onGenerated(response);
    } catch (caught) {
      setError(caught?.message || "Unable to generate project tasks. Retry after reviewing the project and template.");
    } finally {
      setBusy(false);
    }
  }

  return <div className="grid gap-4">
    <section className="rounded-2xl border border-slate-200 bg-white p-4 sm:p-5">
      <div className="flex items-start gap-3"><span className="grid size-10 shrink-0 place-items-center rounded-xl bg-blue-50 text-blue-700"><Layers3 size={18}/></span><div className="min-w-0"><h3 className="font-black text-slate-950">Selected published template</h3><p className="mt-1 text-xs leading-5 text-slate-500">This action copies template tasks into a project-owned draft snapshot. It does not activate or baseline them.</p></div></div>
      <div className="mt-4 grid gap-3 rounded-xl border border-slate-200 bg-slate-50 p-4 sm:grid-cols-3">
        <div><span className="block text-[10px] font-black uppercase tracking-wider text-slate-400">Template</span><strong className="mt-1 block text-sm text-slate-900">{selectedTemplate?.template_name || "Published template"}</strong><span className="text-xs text-slate-500">{selectedTemplate?.template_code || project.template_version_id}</span></div>
        <div><span className="block text-[10px] font-black uppercase tracking-wider text-slate-400">Version</span><strong className="mt-1 block text-sm text-slate-900">{selectedTemplate ? `Version ${selectedTemplate.version_no}` : "Attached version"}</strong><span className="text-xs text-slate-500">Published reference</span></div>
        <div><span className="block text-[10px] font-black uppercase tracking-wider text-slate-400">Duration</span><strong className="mt-1 block text-sm text-slate-900">{selectedTemplate?.duration_days ? `${selectedTemplate.duration_days} days` : "Controlled duration"}</strong><span className="text-xs text-slate-500">No baseline dates yet</span></div>
      </div>
    </section>

    {(result || existingCount) ? <><section className="rounded-2xl border border-emerald-200 bg-emerald-50 p-4 sm:p-5" role="status">
      <div className="flex items-start gap-3"><span className="grid size-10 shrink-0 place-items-center rounded-xl bg-white text-emerald-700"><Check size={18}/></span><div><h3 className="font-black text-emerald-950">Draft tasks already generated</h3><p className="mt-1 text-sm text-emerald-800"><strong>{result?.generated_task_count || existingCount} template-derived tasks</strong> are available for Template Review.</p><p className="mt-1 text-xs text-emerald-700">The project remains Draft. Retrying is safe and creates no duplicates.</p></div></div>
    </section>{showReview && <ProjectTemplateReview projectId={project.id} user={user} projectStatus={project.status}/>}</> : canGenerate ? <section className="rounded-2xl border border-blue-200 bg-blue-50/60 p-4 sm:p-5">
      <h3 className="font-black text-slate-950">Generate controlled draft tasks</h3><p className="mt-1 text-sm leading-6 text-slate-600">Copy mandatory and conditional tasks exactly from the selected published template. Dependencies, gates, activation and baseline dates are not created by this action.</p>
      {error && <div className="mt-4 rounded-xl border border-rose-200 bg-rose-50 p-3 text-sm font-bold text-rose-700" role="alert">{error}</div>}
      <label className="mt-4 flex cursor-pointer items-start gap-3 rounded-xl border border-blue-200 bg-white p-3 text-sm text-slate-700"><input type="checkbox" checked={confirmed} disabled={busy} onChange={event => setConfirmed(event.target.checked)} className="mt-0.5 size-4"/><span>I confirm that the selected published template is correct and understand the project will remain Draft.</span></label>
      <Button className="mt-4 w-full sm:w-auto" loading={busy} disabled={!confirmed || busy} onClick={generate}>{error ? <RotateCcw size={17}/> : <Layers3 size={17}/>} {error ? "Retry generation" : "Generate tasks"}</Button>
    </section> : <section className="rounded-2xl border border-amber-200 bg-amber-50 p-4 text-sm font-bold text-amber-800">{project.status !== "draft" ? "Task generation is available only while the project is Draft." : !project.template_version_id ? "Attach a published template before generating tasks." : "Only Admin can generate draft project tasks."}</section>}
  </div>;
}

function ActivityTimeline({ activity }) {
  if (!activity.length) return <EmptyState icon={<Activity size={20}/>} title="No recorded activity" description="Project changes will appear here automatically."/>;
  return <ol className="grid gap-0">{activity.map((event, index) => <li key={event.id} className="relative grid grid-cols-[36px_minmax(0,1fr)] gap-3 pb-5"><div className="relative grid size-9 place-items-center rounded-full border border-slate-200 bg-white text-blue-700 shadow-sm"><Activity size={15}/>{index < activity.length - 1 && <span className="absolute left-1/2 top-9 h-[calc(100%+4px)] w-px -translate-x-1/2 bg-slate-200"/>}</div><article className="rounded-2xl border border-slate-200 bg-white p-4"><div className="flex flex-wrap items-start justify-between gap-2"><strong className="text-sm text-slate-950">{actionLabel(event.action)}</strong><time className="text-xs text-slate-400">{new Date(event.occurred_at).toLocaleString("en-GB")}</time></div><p className="mt-1 text-sm leading-6 text-slate-600">{event.reason}</p><span className="mt-2 block text-xs font-bold text-slate-400">{event.actor_name}</span></article></li>)}</ol>;
}

export function ProjectDetailModal({ projectId, references, templates = [], user, onClose, onEdit, onChanged, onDeleted }) {
  const [project, setProject] = useState(null);
  const [activity, setActivity] = useState([]);
  const [tab, setTab] = useState("overview");
  const [error, setError] = useState("");
  async function load() {
    try { const [detail, events] = await Promise.all([projectsApi.detail(projectId), projectsApi.activity(projectId)]); setProject(detail); setActivity(events); setError(""); }
    catch (caught) { setError(caught.message); }
  }
  useEffect(() => { load(); }, [projectId]);
  const canEdit = useMemo(() => project && (user.role === "admin" || project.memberships.some(item => item.project_role === "project_manager" && item.user_id === user.id)), [project, user]);
  const detailTabs = [["overview", CalendarDays, "Overview"], ...(!["supervisor", "internal_employee"].includes(user.role) ? [["template-review", Layers3, "Template Review"], ["dependencies", Layers3, "Dependencies"], ["external-gates", ShieldCheck, "External Gates"]] : []), ["team", UsersRound, "Team"], ["activity", Activity, "Activity"]];
  useEffect(() => { if (["supervisor", "internal_employee"].includes(user.role) && ["template-review", "dependencies", "external-gates"].includes(tab)) setTab("overview"); }, [tab, user.role]);
  async function changed() { await load(); await onChanged(); }
  if (!project) return <Modal title="Project" subtitle="Loading controlled project record..." onClose={onClose}>{error || "Loading..."}</Modal>;
  return <Modal hideHeader title={project.name} onClose={onClose} className="sm:max-w-5xl" bodyClassName="bg-slate-50">
    <header className="sticky top-0 z-20 border-b border-slate-200 bg-white/95 px-4 py-4 backdrop-blur sm:px-6"><div className="flex items-start justify-between gap-4"><div className="min-w-0"><div className="flex flex-wrap items-center gap-2"><span className="text-[10px] font-black uppercase tracking-[.18em] text-blue-700">{project.code}</span><Pill tone={statusTone[project.status]}>{project.status.replace("_", " ")}</Pill></div><h2 className="mt-1 truncate text-xl font-black tracking-tight text-slate-950 sm:text-2xl">{project.name}</h2><p className="mt-1 truncate text-sm text-slate-500">{project.client_name}</p></div><div className="flex shrink-0 gap-2">{canEdit && <Button size="icon" variant="secondary" aria-label="Edit project" onClick={() => onEdit(project)}><Pencil size={17}/></Button>}<button className="grid size-11 place-items-center rounded-xl bg-slate-950 text-white hover:bg-slate-800" onClick={onClose} aria-label="Close project">X</button></div></div><nav className="mt-4 flex gap-1 overflow-x-auto rounded-xl bg-slate-100 p-1" aria-label="Project details">{detailTabs.map(([key, Icon, label]) => <button key={key} onClick={() => setTab(key)} className={`inline-flex min-h-10 flex-1 items-center justify-center gap-2 whitespace-nowrap rounded-lg px-3 text-xs font-black transition ${tab === key ? "bg-white text-slate-950 shadow-sm" : "text-slate-500 hover:text-slate-950"}`}><Icon size={15}/>{label}</button>)}</nav></header>
    <div className="p-4 sm:p-6">{error && <div className="mb-4 rounded-xl border border-rose-200 bg-rose-50 p-3 text-sm font-bold text-rose-700">{error}</div>}{tab === "overview" && <div className="grid gap-4"><Overview project={project}/><TemplateReview project={project} activity={activity} templates={templates} user={user} showReview={false} onGenerated={async () => { await changed(); setTab("template-review"); }}/><Lifecycle project={project} user={user} onChanged={changed} onDeleted={onDeleted}/></div>} {tab === "template-review" && <TemplateReview project={project} activity={activity} templates={templates} user={user} onGenerated={async () => { await changed(); setTab("template-review"); }}/>} {tab === "dependencies" && <ProjectDependencies project={project} user={user}/>} {tab === "external-gates" && <ProjectExternalGates project={project} user={user}/>} {tab === "team" && <Team project={project} references={references} user={user} onChanged={changed}/>} {tab === "activity" && <ActivityTimeline activity={activity}/>}</div>
  </Modal>;
}
