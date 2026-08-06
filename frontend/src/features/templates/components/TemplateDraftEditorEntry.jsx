import { AlertTriangle, ArrowDown, ArrowLeft, ArrowRight, ArrowUp, BookOpenCheck, CalendarDays, GitBranch, GripVertical, PencilLine, Plus, RefreshCw, Rocket, Save, ShieldAlert, Trash2 } from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { templatesApi } from "../../../api/templatesApi";
import { Alert, Button, EmptyState, LoadingSpinner, Modal, Pill } from "../../../components/ui";
import { formatTemplateDate, statusTone } from "./TemplateCard";
import { formatPlannedDays } from "./TemplateTaskCard";
import { TemplateTaskEditorModal } from "./TemplateTaskEditorModal";
import { TemplateDependencyEditorModal } from "./TemplateDependencyEditorModal";
import { dependencyTypeLabel } from "./TemplateDependencyCard";
import { TemplateGateEditorModal } from "./TemplateGateEditorModal";
import { gateMappingLabel } from "./TemplateGateCard";
import { TemplateValidationPublishPanel } from "./TemplateValidationPublishPanel";
import { nextStructuredCode } from "./templateAuthoringOptions";

function apiMessage(error) {
  const detail = error?.details?.detail;
  if (detail?.code === "stale_template_version") return "This draft changed in another session. Refresh before trying again.";
  if (typeof detail?.message === "string") return detail.message;
  if (typeof error?.message === "string") return error.message;
  return "The draft could not be updated.";
}

async function loadEveryDependency(versionId) {
  const first = await templatesApi.listDependencies(versionId, { page:1, page_size:100 });
  if ((first.pagination?.total_pages || 1) <= 1) return first.items;
  const pages = await Promise.all(Array.from({ length:first.pagination.total_pages - 1 }, (_, index) =>
    templatesApi.listDependencies(versionId, { page:index + 2, page_size:100 })
  ));
  return [first, ...pages].flatMap(page => page.items);
}

async function loadEveryGate(versionId) {
  const first = await templatesApi.listGates(versionId, { page:1, page_size:100 });
  if ((first.pagination?.total_pages || 1) <= 1) return first.items;
  const pages = await Promise.all(Array.from({ length:first.pagination.total_pages - 1 }, (_, index) => templatesApi.listGates(versionId, { page:index + 2, page_size:100 })));
  return [first, ...pages].flatMap(page => page.items);
}

async function loadEveryTask(versionId) {
  const first = await templatesApi.listTasks(versionId, { page:1, page_size:100 });
  if ((first.pagination?.total_pages || 1) <= 1) return first.items;
  const pages = await Promise.all(Array.from({ length:first.pagination.total_pages - 1 }, (_, index) =>
    templatesApi.listTasks(versionId, { page:index + 2, page_size:100 })
  ));
  return [first, ...pages].flatMap(page => page.items);
}

function TaskRow({ task, index, count, disableMove, onEdit, onDelete, onMove }) {
  const isGate = task.task_kind === "approval_gate";
  return <article data-testid={"draft-task-" + task.code} className="rounded-2xl border border-slate-200 bg-white p-4 shadow-[0_8px_28px_rgba(15,23,42,.05)]">
    <div className="flex items-start gap-3">
      <span className="mt-0.5 hidden text-slate-300 sm:block"><GripVertical size={18}/></span>
      <div className="min-w-0 flex-1">
        <div className="flex flex-wrap items-center gap-2"><span className="font-mono text-xs font-black text-blue-700">{task.code}</span><Pill tone={task.applicability === "conditional" ? "orange" : "blue"}>{task.applicability}</Pill><Pill tone={isGate ? "violet" : "gray"}>{isGate ? "External approval gate" : "Standard work"}</Pill><span className="text-xs font-bold text-slate-400">Sequence {index + 1}</span></div>
        <h3 className="mt-2 text-sm font-black leading-5 text-slate-950">{task.title}</h3>
        <div className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-xs font-semibold text-slate-500"><span>{formatPlannedDays(task)}</span><span>{task.phase || "No phase"}</span><span>{task.category || "No category"}</span></div>
      </div>
      <div className="hidden items-center gap-1 sm:flex">
        <Button size="icon" variant="ghost" aria-label={"Move " + task.code + " up"} disabled={disableMove || index===0} onClick={() => onMove(index,-1)}><ArrowUp size={16}/></Button>
        <Button size="icon" variant="ghost" aria-label={"Move " + task.code + " down"} disabled={disableMove || index===count-1} onClick={() => onMove(index,1)}><ArrowDown size={16}/></Button>
        <Button size="icon" variant="secondary" aria-label={"Edit " + task.code} onClick={() => onEdit(task)}><PencilLine size={16}/></Button>
        <Button size="icon" variant="danger" aria-label={"Delete " + task.code} onClick={() => onDelete(task)}><Trash2 size={16}/></Button>
      </div>
    </div>
    <div className="mt-4 grid grid-cols-4 gap-2 border-t border-slate-100 pt-3 sm:hidden">
      <Button size="sm" variant="ghost" aria-label={"Move " + task.code + " up"} disabled={disableMove || index===0} onClick={() => onMove(index,-1)}><ArrowUp size={15}/></Button>
      <Button size="sm" variant="ghost" aria-label={"Move " + task.code + " down"} disabled={disableMove || index===count-1} onClick={() => onMove(index,1)}><ArrowDown size={15}/></Button>
      <Button size="sm" variant="secondary" aria-label={"Edit " + task.code} onClick={() => onEdit(task)}><PencilLine size={15}/></Button>
      <Button size="sm" variant="danger" aria-label={"Delete " + task.code} onClick={() => onDelete(task)}><Trash2 size={15}/></Button>
    </div>
  </article>;
}

function DeleteTaskModal({ task, busy, error, onClose, onConfirm }) {
  const detail = error?.details?.detail;
  const dependencies = detail?.dependencies || [];
  const gates = detail?.gate_mappings || [];
  const referenced = detail?.code === "template_task_referenced";
  return <Modal title={"Delete " + task.code + "?"} subtitle="Draft task deletion is permanent." onClose={onClose} className="sm:max-w-lg">
    <div className="grid gap-5">
      {error && <Alert tone="danger" role="alert"><AlertTriangle size={18}/><div><strong>{referenced ? "Task is still referenced" : "Task was not deleted"}</strong><span className="mt-1 block">{referenced ? "Remove or remap the references below before deleting this task." : apiMessage(error)}</span></div></Alert>}
      {referenced && <div className="grid gap-3 rounded-2xl border border-rose-200 bg-rose-50 p-4 text-sm text-rose-950">
        {dependencies.length > 0 && <div><strong>Dependencies ({dependencies.length})</strong><ul className="mt-2 list-disc space-y-1 pl-5">{dependencies.map((item,index) => <li key={item.id || index}>{item.predecessor_code && item.successor_code ? item.predecessor_code + " → " + item.successor_code : (item.relationship || "dependency").replaceAll("_"," ") + " · related task " + item.other_task_id}</li>)}</ul></div>}
        {gates.length > 0 && <div><strong>External gate mappings ({gates.length})</strong><ul className="mt-2 list-disc space-y-1 pl-5">{gates.map((item,index) => <li key={item.id || index}>{item.gate_code || item.code || "Mapped gate"}</li>)}</ul></div>}
      </div>}
      {!referenced && <p className="text-sm leading-6 text-slate-600">This will remove <strong className="text-slate-950">{task.title}</strong> from the draft. Published versions are not affected.</p>}
      <div className="flex flex-col-reverse gap-2 sm:flex-row sm:justify-end"><Button variant="secondary" onClick={onClose}>Cancel</Button>{!referenced && <Button variant="danger" loading={busy} onClick={onConfirm}><Trash2 size={16}/> Delete task</Button>}</div>
    </div>
  </Modal>;
}


function DependencyRow({ dependency, onEdit, onDelete }) {
  return <article data-testid={"draft-dependency-" + dependency.id} className="rounded-2xl border border-slate-200 bg-white p-4 shadow-[0_8px_28px_rgba(15,23,42,.05)]">
    <div className="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
      <div className="min-w-0 flex-1">
        <div className="flex flex-wrap items-center gap-2"><span className="text-[10px] font-black uppercase tracking-[.16em] text-cyan-700">Dependency {dependency.sequence_no}</span><Pill tone="blue">{dependencyTypeLabel(dependency.dependency_type)}</Pill><Pill tone={dependency.blocking ? "red" : "gray"}>{dependency.blocking ? "Blocking" : "Non-blocking"}</Pill></div>
        <div className="mt-4 grid grid-cols-[minmax(0,1fr)_32px_minmax(0,1fr)] items-center gap-2">
          <div><b className="font-mono text-xs text-blue-700">{dependency.predecessor?.code || "Missing"}</b><p className="mt-1 text-sm font-bold text-slate-950">{dependency.predecessor?.title || "Missing predecessor"}</p></div>
          <span className="grid size-8 place-items-center rounded-full bg-slate-100 text-slate-500"><ArrowRight size={16}/></span>
          <div><b className="font-mono text-xs text-blue-700">{dependency.successor?.code || "Missing"}</b><p className="mt-1 text-sm font-bold text-slate-950">{dependency.successor?.title || "Missing successor"}</p></div>
        </div>
        <p className="mt-4 border-t border-slate-100 pt-3 text-xs font-semibold leading-5 text-slate-600">{dependency.rule_text || "No rule text recorded."}</p>
      </div>
      <div className="grid grid-cols-2 gap-2 sm:flex">
        <Button size="sm" variant="secondary" aria-label={"Edit dependency " + dependency.sequence_no} onClick={() => onEdit(dependency)}><PencilLine size={15}/> Edit</Button>
        <Button size="sm" variant="danger" aria-label={"Delete dependency " + dependency.sequence_no} onClick={() => onDelete(dependency)}><Trash2 size={15}/> Delete</Button>
      </div>
    </div>
  </article>;
}

function DeleteDependencyModal({ dependency, busy, error, onClose, onConfirm }) {
  return <Modal title="Delete dependency?" subtitle="The draft relationship will be removed." onClose={onClose} className="sm:max-w-lg">
    <div className="grid gap-5">
      {error && <Alert tone="danger" role="alert"><AlertTriangle size={18}/><div><strong>Dependency was not deleted</strong><span className="mt-1 block">{apiMessage(error)}</span></div></Alert>}
      <p className="text-sm leading-6 text-slate-600"><strong className="text-slate-950">{dependency.predecessor?.code || "Predecessor"}</strong> → <strong className="text-slate-950">{dependency.successor?.code || "Successor"}</strong> will no longer constrain this draft.</p>
      <div className="flex flex-col-reverse gap-2 sm:flex-row sm:justify-end"><Button variant="secondary" onClick={onClose}>Cancel</Button><Button variant="danger" loading={busy} onClick={onConfirm}><Trash2 size={16}/> Delete dependency</Button></div>
    </div>
  </Modal>;
}

function GateRow({ gate, onEdit, onDelete }) {
 const broad=gate.mapping_classification==="broad_text";
 return <article data-testid={`draft-gate-${gate.id}`} className="rounded-2xl border border-slate-200 bg-white p-4 shadow-[0_8px_28px_rgba(15,23,42,.05)]"><div className="flex items-start justify-between gap-3"><div className="min-w-0"><div className="flex flex-wrap items-center gap-2"><span className="font-mono text-xs font-black text-blue-700">{gate.code}</span><Pill tone={gate.mapping_classification==="exact"?"blue":"orange"}>{gateMappingLabel(gate.mapping_classification)}</Pill>{gate.requires_configuration&&<Pill tone="orange">Requires configuration</Pill>}</div><h3 className="mt-2 text-sm font-black text-slate-950">{gate.approval_name}</h3><p className="mt-1 text-xs font-semibold text-slate-500">{gate.external_party||"External party not specified"}</p>{broad&&<div className="mt-3 rounded-xl border border-amber-200 bg-amber-50 p-3 text-xs text-amber-900"><strong>Broad original text</strong><p className="mt-1 font-semibold">{gate.broad_mapping_text}</p><p className="mt-1">No exact links inferred.</p></div>}{gate.mapping_classification==="exact"&&<p className="mt-3 text-xs font-bold text-slate-600">{gate.affected_tasks?.length||gate.task_ids?.length||0} explicit task mapping(s)</p>}</div><div className="hidden gap-1 sm:flex"><Button size="icon" variant="secondary" aria-label={`Edit gate ${gate.code}`} onClick={()=>onEdit(gate)}><PencilLine size={16}/></Button><Button size="icon" variant="danger" aria-label={`Delete gate ${gate.code}`} onClick={()=>onDelete(gate)}><Trash2 size={16}/></Button></div></div><div className="mt-4 grid grid-cols-2 gap-2 border-t border-slate-100 pt-3 sm:hidden"><Button size="sm" variant="secondary" aria-label={`Edit gate ${gate.code}`} onClick={()=>onEdit(gate)}><PencilLine size={15}/> Edit</Button><Button size="sm" variant="danger" aria-label={`Delete gate ${gate.code}`} onClick={()=>onDelete(gate)}><Trash2 size={15}/> Delete</Button></div></article>;
}
function DeleteGateModal({gate,busy,error,onClose,onConfirm}){return <Modal title={`Delete ${gate.code}?`} subtitle="Only this gate and its own mapping rows will be removed." onClose={onClose} className="sm:max-w-lg"><div className="grid gap-5">{error&&<Alert tone="danger" role="alert"><AlertTriangle size={18}/><div><strong>Gate was not deleted</strong><span className="mt-1 block">{apiMessage(error)}</span></div></Alert>}<Alert tone="warning"><ShieldAlert size={18}/><span>Tasks are not deleted or changed by this action.</span></Alert><p className="text-sm text-slate-600"><strong className="text-slate-950">{gate.approval_name}</strong></p><div className="flex flex-col-reverse gap-2 sm:flex-row sm:justify-end"><Button variant="secondary" onClick={onClose}>Cancel</Button><Button variant="danger" loading={busy} onClick={onConfirm}><Trash2 size={16}/> Delete gate</Button></div></div></Modal>}

export function TemplateDraftEditorEntry({ summary: initialSummary, user, onBack, onPublished }) {
  const [summary, setSummary] = useState(initialSummary);
  const [activeEditorTab, setActiveEditorTab] = useState("tasks");
  const [taskKindFilter, setTaskKindFilter] = useState("all");
  const [tasks, setTasks] = useState([]);
  const [dependencies, setDependencies] = useState([]);
  const [gates, setGates] = useState([]);
  const [savedOrder, setSavedOrder] = useState([]);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState(null);
  const [mutationError, setMutationError] = useState(null);
  const [editorTask, setEditorTask] = useState(undefined);
  const [editorOpen, setEditorOpen] = useState(false);
  const [formDirty, setFormDirty] = useState(false);
  const [deleteTask, setDeleteTask] = useState(null);
  const [deleteError, setDeleteError] = useState(null);
  const [deleting, setDeleting] = useState(false);
  const [savingOrder, setSavingOrder] = useState(false);
  const [dependencyEditorOpen, setDependencyEditorOpen] = useState(false);
  const [editorDependency, setEditorDependency] = useState(undefined);
  const [deleteDependency, setDeleteDependency] = useState(null);
  const [dependencyDeleteError, setDependencyDeleteError] = useState(null);
  const [deletingDependency, setDeletingDependency] = useState(false);
  const [gateEditorOpen,setGateEditorOpen]=useState(false);
  const [editorGate,setEditorGate]=useState(undefined);
  const [deleteGate,setDeleteGate]=useState(null);
  const [gateDeleteError,setGateDeleteError]=useState(null);
  const [deletingGate,setDeletingGate]=useState(false);
  const refreshPromiseRef = useRef(null);
  const editable = user?.role === "super_admin" && summary?.status === "draft";
  const reorderDirty = useMemo(() => tasks.map(task => task.id).join("|") !== savedOrder.join("|"), [savedOrder,tasks]);
  const dirty = formDirty || reorderDirty;
  const gateTaskCount = useMemo(() => tasks.filter(task => task.task_kind === "approval_gate").length, [tasks]);
  const standardTaskCount = tasks.length - gateTaskCount;
  const visibleTasks = useMemo(() => taskKindFilter === "all" ? tasks
    : tasks.filter(task => (task.task_kind === "approval_gate") === (taskKindFilter === "approval_gate")), [tasks,taskKindFilter]);

  const refresh = useCallback(() => {
    if (refreshPromiseRef.current) return refreshPromiseRef.current;
    setLoading(true); setLoadError(null); setMutationError(null);
    const request = Promise.all([templatesApi.getVersion(initialSummary.version_id),loadEveryTask(initialSummary.version_id),loadEveryDependency(initialSummary.version_id),loadEveryGate(initialSummary.version_id)])
      .then(([nextSummary,nextTasks,nextDependencies,nextGates]) => {
        setSummary(nextSummary);
        const ordered=[...nextTasks].sort((a,b)=>a.sequence_no-b.sequence_no || a.code.localeCompare(b.code));
        setTasks(ordered); setSavedOrder(ordered.map(task=>task.id));
        setDependencies([...nextDependencies].sort((a,b)=>a.sequence_no-b.sequence_no || String(a.id).localeCompare(String(b.id))));
        setGates([...nextGates].sort((a,b)=>a.sequence_no-b.sequence_no || String(a.id).localeCompare(String(b.id))));
      })
      .catch(error => { setLoadError(error); })
      .finally(() => { setLoading(false); refreshPromiseRef.current=null; });
    refreshPromiseRef.current=request;
    return request;
  }, [initialSummary.version_id]);

  useEffect(() => { refresh(); }, [refresh]);
  useEffect(() => {
    setSummary(current => current?.version_id === initialSummary.version_id
      ? { ...current, ...initialSummary }
      : initialSummary);
  }, [
    initialSummary.version_id, initialSummary.revision_token,
    initialSummary.status, initialSummary.updated_at,
  ]);

  useEffect(() => {
    if (!dirty) return undefined;
    const warn = event => { event.preventDefault(); event.returnValue=""; };
    window.addEventListener("beforeunload",warn);
    return () => window.removeEventListener("beforeunload",warn);
  }, [dirty]);

  function leave() { if (!dirty || window.confirm("You have unsaved draft changes. Leave without saving?")) onBack(); }
  function move(index,direction) {
    const target=index+direction;
    if(target<0 || target>=tasks.length) return;
    setTasks(current => { const next=[...current]; [next[index],next[target]]=[next[target],next[index]]; return next; });
  }
  function openAdd(){setEditorTask(null);setEditorOpen(true);}
  function openEdit(task){setEditorTask(task);setEditorOpen(true);}

  async function saveTask(payload,task) {
    const response=task ? await templatesApi.updateTask(summary.version_id,task.id,payload) : await templatesApi.createTask(summary.version_id,payload);
    setSummary(current=>({...current,revision_token:response.revision_token}));
    setEditorOpen(false);setFormDirty(false);
    await refresh();
  }

  async function confirmDelete() {
    if(deleting) return;
    setDeleting(true);setDeleteError(null);
    try {
      const response=await templatesApi.deleteTask(summary.version_id,deleteTask.id,summary.revision_token);
      setSummary(current=>({...current,revision_token:response.revision_token}));
      setDeleteTask(null);
      await refresh();
    } catch(error){setDeleteError(error);}
    finally{setDeleting(false);}
  }

  async function saveOrder() {
    if(!reorderDirty || savingOrder) return;
    setSavingOrder(true);setMutationError(null);
    try {
      const response=await templatesApi.reorderTasks(summary.version_id,{revision_token:summary.revision_token,items:tasks.map((task,index)=>({task_id:task.id,sequence_no:index+1}))});
      setSummary(current=>({...current,revision_token:response.revision_token}));
      setSavedOrder(tasks.map(task=>task.id));
      await refresh();
    } catch(error){setMutationError(error);}
    finally{setSavingOrder(false);}
  }

  function openAddDependency(){setEditorDependency(null);setDependencyEditorOpen(true);}
  function openEditDependency(dependency){setEditorDependency(dependency);setDependencyEditorOpen(true);}

  async function saveDependency(payload, dependency) {
    const response = dependency
      ? await templatesApi.updateDependency(summary.version_id, dependency.id, payload)
      : await templatesApi.createDependency(summary.version_id, payload);
    setSummary(current => ({ ...current, revision_token:response.revision_token }));
    setDependencyEditorOpen(false); setFormDirty(false);
    await refresh();
  }

  async function confirmDependencyDelete() {
    if (deletingDependency) return;
    setDeletingDependency(true); setDependencyDeleteError(null);
    try {
      const response = await templatesApi.deleteDependency(summary.version_id, deleteDependency.id, summary.revision_token);
      setSummary(current => ({ ...current, revision_token:response.revision_token }));
      setDeleteDependency(null);
      await refresh();
    } catch (error) { setDependencyDeleteError(error); }
    finally { setDeletingDependency(false); }
  }


  function openAddGate(){setEditorGate(null);setGateEditorOpen(true);}
  function openEditGate(gate){setEditorGate(gate);setGateEditorOpen(true);}
  async function saveGate(payload,gate,initialJson){
    if(!gate){const response=await templatesApi.createGate(summary.version_id,payload);setSummary(c=>({...c,revision_token:response.revision_token}));}
    else {
      const initial=JSON.parse(initialJson); const metadataKeys=["code","approval_name","description","external_party","required_by_type","required_by_value","impact","sequence_no"];
      const changes={revision_token:summary.revision_token}; metadataKeys.forEach(key=>{const old=initial[key]??null,newValue=payload[key]??null;if(old!==newValue)changes[key]=newValue;});
      let token=summary.revision_token;
      if(Object.keys(changes).length>1){const updated=await templatesApi.updateGate(summary.version_id,gate.id,changes);token=updated.revision_token;}
      const oldIds=[...(initial.task_ids||[])].map(String).sort(); const newIds=[...(payload.task_ids||[])].map(String).sort();
      const mappingChanged=initial.mapping_classification!==payload.mapping_classification||initial.broad_mapping_text!==payload.broad_mapping_text||JSON.stringify(oldIds)!==JSON.stringify(newIds);
      if(mappingChanged){const mapped=await templatesApi.configureGateMappings(summary.version_id,gate.id,{mapping_classification:payload.mapping_classification,broad_mapping_text:payload.broad_mapping_text,task_ids:payload.task_ids,revision_token:token});token=mapped.revision_token;}
      setSummary(c=>({...c,revision_token:token}));
    }
    setGateEditorOpen(false);setFormDirty(false);await refresh();
  }
  async function confirmGateDelete(){if(deletingGate)return;setDeletingGate(true);setGateDeleteError(null);try{const response=await templatesApi.deleteGate(summary.version_id,deleteGate.id,summary.revision_token);setSummary(c=>({...c,revision_token:response.revision_token}));setDeleteGate(null);await refresh();}catch(error){setGateDeleteError(error)}finally{setDeletingGate(false)}}


  if(!editable) return <Alert tone="danger"><AlertTriangle size={18}/><div><strong>Draft authoring is unavailable</strong><span className="mt-1 block">Only Super Admin can edit a draft template version.</span></div></Alert>;

  return <section className="grid gap-5" data-testid="template-draft-editor">
    <header className="relative overflow-hidden rounded-[26px] bg-slate-950 p-5 text-white shadow-[0_24px_70px_rgba(15,23,42,.18)] sm:p-7">
      <div aria-hidden="true" className="absolute -right-16 -top-20 size-64 rounded-full border-[38px] border-amber-400/10"/>
      <div className="relative">
        <Button variant="ghost" className="-ml-3 text-slate-300 hover:bg-white/10 hover:text-white" onClick={leave}><ArrowLeft size={17}/> Back to draft details</Button>
        <div className="mt-5 flex flex-col gap-5 lg:flex-row lg:items-end lg:justify-between">
          <div><div className="flex flex-wrap items-center gap-2"><span className="font-mono text-[11px] font-black uppercase tracking-[.18em] text-blue-300">{summary.template_code}</span><Pill tone={statusTone(summary.status)}>{summary.status}</Pill><span className="rounded-full bg-amber-300/15 px-2.5 py-1 text-[10px] font-black uppercase tracking-wider text-amber-200">Editable working copy</span></div><h2 className="mt-3 text-2xl font-black tracking-[-.04em] sm:text-4xl">Draft task authoring</h2><p className="mt-2 max-w-2xl text-sm leading-6 text-slate-300">{summary.template_name} · Version {summary.version_no}</p></div>
          <div className="grid grid-cols-2 gap-2 text-xs font-bold"><span className="rounded-xl border border-white/10 bg-white/[.07] px-3.5 py-3"><b className="block text-white">{summary.updated_at ? formatTemplateDate(summary.updated_at) : "Not available"}</b><small className="text-slate-400">Last updated</small></span><span className="rounded-xl border border-white/10 bg-white/[.07] px-3.5 py-3"><b className="block font-mono text-white">{summary.revision_token ? summary.revision_token.slice(-10) : "Loading"}</b><small className="text-slate-400">Revision</small></span></div>
        </div>
      </div>
    </header>

    <nav aria-label="Draft editor sections" className="grid grid-cols-1 gap-2 rounded-2xl sm:grid-cols-2 lg:grid-cols-4 border border-slate-200 bg-white p-2">
      <Button variant={activeEditorTab === "tasks" ? "primary" : "ghost"} onClick={() => setActiveEditorTab("tasks")}><BookOpenCheck size={17}/> Tasks ({tasks.length})</Button>
      <Button variant={activeEditorTab === "dependencies" ? "primary" : "ghost"} onClick={() => setActiveEditorTab("dependencies")}><GitBranch size={17}/> Dependencies ({dependencies.length})</Button>
      <Button variant={activeEditorTab === "gates" ? "primary" : "ghost"} onClick={() => setActiveEditorTab("gates")}><ShieldAlert size={17}/> External Gates ({gates.length})</Button>
      <Button variant={activeEditorTab === "validation" ? "primary" : "ghost"} onClick={() => setActiveEditorTab("validation")}><Rocket size={17}/> Validate & Publish</Button>
    </nav>

    {activeEditorTab === "tasks" ? <>
      <div className="flex flex-col gap-3 rounded-2xl border border-amber-200 bg-amber-50 p-4 sm:flex-row sm:items-center sm:justify-between"><div className="flex items-start gap-3"><BookOpenCheck className="mt-0.5 shrink-0 text-amber-700" size={19}/><div><strong className="text-amber-950">Tasks · Draft authoring</strong><p className="mt-1 text-xs font-semibold leading-5 text-amber-800">Create, edit and order this working copy. Dependencies and gate references are never removed automatically.</p></div></div><Button className="w-full sm:w-auto" onClick={openAdd}><Plus size={17}/> Add task</Button></div>
      {mutationError && <Alert tone="danger" role="alert" className="items-center"><div><strong>Draft update failed</strong><span className="mt-1 block">{apiMessage(mutationError)}</span></div><Button variant="secondary" size="sm" onClick={refresh}><RefreshCw size={15}/> Refresh draft</Button></Alert>}
      {tasks.length > 0 && <div className="grid grid-cols-1 gap-2 rounded-2xl border border-slate-200 bg-white p-2 sm:grid-cols-3" role="tablist" aria-label="Filter tasks by kind">
        <Button variant={taskKindFilter === "all" ? "primary" : "ghost"} size="sm" onClick={() => setTaskKindFilter("all")}>All ({tasks.length})</Button>
        <Button variant={taskKindFilter === "work" ? "primary" : "ghost"} size="sm" onClick={() => setTaskKindFilter("work")}>Standard work ({standardTaskCount})</Button>
        <Button variant={taskKindFilter === "approval_gate" ? "primary" : "ghost"} size="sm" onClick={() => setTaskKindFilter("approval_gate")}>External approval gate ({gateTaskCount})</Button>
      </div>}
      {tasks.length > 0 && taskKindFilter !== "all" && <p className="text-xs font-semibold text-slate-500">Reordering is only available from the "All" tab, since sequence spans both kinds.</p>}
      {loading ? <div className="grid min-h-64 place-items-center rounded-2xl border border-slate-200 bg-white"><LoadingSpinner label="Loading draft tasks..."/></div> : loadError ? <Alert tone="danger" className="items-center"><div><strong>Draft tasks unavailable</strong><span className="mt-1 block">{apiMessage(loadError)}</span></div><Button variant="secondary" size="sm" onClick={refresh}><RefreshCw size={15}/> Retry</Button></Alert> : tasks.length===0 ? <EmptyState className="min-h-64 bg-white" title="This draft has no tasks" description="Add the first controlled task to begin authoring." action={<Button onClick={openAdd}><Plus size={16}/> Add first task</Button>}/> : visibleTasks.length===0 ? <EmptyState className="min-h-64 bg-white" title="No tasks of this kind yet" description="Switch tabs or add a task and set its kind."/> : <div className="grid gap-3">{visibleTasks.map(task=>{const index=tasks.indexOf(task);return <TaskRow key={task.id} task={task} index={index} count={tasks.length} disableMove={taskKindFilter !== "all"} onEdit={openEdit} onDelete={task=>{setDeleteTask(task);setDeleteError(null);}} onMove={move}/>;})}</div>}
      {!loading && tasks.length>0 && <footer className="sticky bottom-3 z-10 flex flex-col gap-3 rounded-2xl border border-slate-200 bg-white/95 p-3 shadow-[0_18px_50px_rgba(15,23,42,.16)] backdrop-blur sm:flex-row sm:items-center sm:justify-between"><div className="px-1"><strong className="text-sm text-slate-950">{tasks.length} draft task{tasks.length===1?"":"s"}</strong><p className="mt-0.5 text-xs font-semibold text-slate-500">{reorderDirty ? "Order changed — save to create a new revision." : "Sequence is saved."}</p></div><div className="grid grid-cols-2 gap-2"><Button variant="secondary" disabled={!reorderDirty||savingOrder} onClick={()=>{const restored=savedOrder.map(id=>tasks.find(task=>task.id===id)).filter(Boolean);setTasks(restored);}}>Cancel order</Button><Button loading={savingOrder} disabled={!reorderDirty} onClick={saveOrder}><Save size={16}/> Save order</Button></div></footer>}
    </> : activeEditorTab === "dependencies" ? <>
      <div className="flex flex-col gap-3 rounded-2xl border border-cyan-200 bg-cyan-50 p-4 sm:flex-row sm:items-center sm:justify-between"><div className="flex items-start gap-3"><GitBranch className="mt-0.5 shrink-0 text-cyan-700" size={19}/><div><strong className="text-cyan-950">Dependencies · Draft authoring</strong><p className="mt-1 text-xs font-semibold leading-5 text-cyan-800">Add explicit task relationships. Cycles and duplicate relationships are rejected by the backend.</p></div></div><Button className="w-full sm:w-auto" onClick={openAddDependency} disabled={tasks.length < 2}><Plus size={17}/> Add relationship</Button></div>
      {loading ? <div className="grid min-h-64 place-items-center rounded-2xl border border-slate-200 bg-white"><LoadingSpinner label="Loading draft dependencies..."/></div> : loadError ? <Alert tone="danger" className="items-center"><div><strong>Draft dependencies unavailable</strong><span className="mt-1 block">{apiMessage(loadError)}</span></div><Button variant="secondary" size="sm" onClick={refresh}><RefreshCw size={15}/> Retry</Button></Alert> : dependencies.length===0 ? <EmptyState className="min-h-64 bg-white" title="This draft has no dependencies" description="Add the first controlled task relationship." action={tasks.length >= 2 ? <Button onClick={openAddDependency}><Plus size={16}/> Add first relationship</Button> : null}/> : <div className="grid gap-3">{dependencies.map(dependency => <DependencyRow key={dependency.id} dependency={dependency} onEdit={openEditDependency} onDelete={item=>{setDeleteDependency(item);setDependencyDeleteError(null);}}/>)}</div>}
       </> : activeEditorTab === "gates" ? <>
      <div className="flex flex-col gap-3 rounded-2xl border border-violet-200 bg-violet-50 p-4 sm:flex-row sm:items-center sm:justify-between"><div className="flex items-start gap-3"><ShieldAlert className="mt-0.5 shrink-0 text-violet-700" size={19}/><div><strong className="text-violet-950">External gates · Draft authoring</strong><p className="mt-1 text-xs font-semibold leading-5 text-violet-800">Configure exact mappings explicitly or preserve broad source wording without inferred task links.</p></div></div><Button className="w-full sm:w-auto" onClick={openAddGate}><Plus size={17}/> Add gate</Button></div>
      {loading ? <div className="grid min-h-64 place-items-center rounded-2xl border border-slate-200 bg-white"><LoadingSpinner label="Loading draft external gates..."/></div> : loadError ? <Alert tone="danger"><strong>Draft gates unavailable</strong><span>{apiMessage(loadError)}</span></Alert> : gates.length===0 ? <EmptyState className="min-h-64 bg-white" title="This draft has no external gates" description="Add the first approval or readiness gate." action={<Button onClick={openAddGate}><Plus size={16}/> Add first gate</Button>}/> : <div className="grid gap-3">{gates.map(gate=><GateRow key={gate.id} gate={gate} onEdit={openEditGate} onDelete={item=>{setDeleteGate(item);setGateDeleteError(null)}}/>)}</div>}
    </> : null}
    <div className={activeEditorTab === "validation" ? "block" : "hidden"} aria-hidden={activeEditorTab !== "validation"}><TemplateValidationPublishPanel summary={summary} onNavigate={setActiveEditorTab} onRefresh={refresh} onPublished={onPublished}/></div>

    {editorOpen && <TemplateTaskEditorModal task={editorTask} tasks={tasks} durationDays={summary.duration_days} revisionToken={summary.revision_token} nextSequence={tasks.length+1} suggestedCode={nextStructuredCode(tasks, "T")} onClose={()=>{setEditorOpen(false);setFormDirty(false);}} onSaved={saveTask} onDirtyChange={setFormDirty}/>}
    {deleteTask && <DeleteTaskModal task={deleteTask} busy={deleting} error={deleteError} onClose={()=>{setDeleteTask(null);setDeleteError(null);}} onConfirm={confirmDelete}/>}
    {dependencyEditorOpen && <TemplateDependencyEditorModal dependency={editorDependency} tasks={tasks} revisionToken={summary.revision_token} nextSequence={dependencies.length+1} onClose={()=>{setDependencyEditorOpen(false);setFormDirty(false);}} onSaved={saveDependency} onDirtyChange={setFormDirty}/>} 
    {deleteDependency && <DeleteDependencyModal dependency={deleteDependency} busy={deletingDependency} error={dependencyDeleteError} onClose={()=>{setDeleteDependency(null);setDependencyDeleteError(null);}} onConfirm={confirmDependencyDelete}/>} 
    {gateEditorOpen && <TemplateGateEditorModal gate={editorGate} gates={gates} tasks={tasks} durationDays={summary.duration_days} revisionToken={summary.revision_token} nextSequence={gates.length+1} suggestedCode={nextStructuredCode(gates, "E")} onClose={()=>{setGateEditorOpen(false);setFormDirty(false)}} onSaved={saveGate} onDirtyChange={setFormDirty}/>} 
    {deleteGate && <DeleteGateModal gate={deleteGate} busy={deletingGate} error={gateDeleteError} onClose={()=>{setDeleteGate(null);setGateDeleteError(null)}} onConfirm={confirmGateDelete}/>} 
  </section>;
}
