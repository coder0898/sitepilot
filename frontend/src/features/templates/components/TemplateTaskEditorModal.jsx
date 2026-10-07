import { AlertTriangle, CalendarDays, Save } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { Alert, Button, Field, Input, Modal, Select, Textarea } from "../../../components/ui";
import { APPROVED_CATEGORIES, APPROVED_PHASES, LEGACY_PHASES, TASK_CLASS_OPTIONS, TASK_KIND_LABELS } from "./templateAuthoringOptions";
import { TemplateChoiceGroup } from "./TemplateChoiceGroup";

const emptyTask = { code:"", sequence_no:"", title:"", description:"", schedule_classification:"execution", planned_start_day:"", planned_end_day:"", phase:"", category:"", applicability:"mandatory", task_class:"", task_kind:"", evidence_required:false, duration_days:"" };
const asForm = (task, nextSequence, suggestedCode) => task ? Object.fromEntries(Object.keys(emptyTask).map(key => [key, task[key] ?? (key === "evidence_required" ? false : "")])) : { ...emptyTask, sequence_no:nextSequence ?? "", code:suggestedCode ?? "" };
const optional = value => String(value ?? "").trim() || null;
function derivedDuration(form){ if(form.schedule_classification!=="execution") return form.duration_days; const start=Number(form.planned_start_day), end=Number(form.planned_end_day); return Number.isInteger(start)&&Number.isInteger(end)&&end>=start ? end-start+1 : ""; }
function errorCopy(error) { const detail=error?.details?.detail; if(detail?.code==="stale_template_version")return "This draft changed in another session. Refresh it before retrying."; return detail?.message||error?.message||"The task could not be saved."; }

const APPLICABILITY_OPTIONS = [
  { value:"mandatory", label:"Yes, every project", detail:"The task is always part of the project plan." },
  { value:"conditional", label:"No, only when it applies", detail:"The PM can remove it from a project before the project starts." },
];

function Section({ title, children }) {
  return <section className="grid gap-4 rounded-2xl border border-slate-200 bg-slate-50 p-4 sm:p-5"><h3 className="text-xs font-black uppercase tracking-[.16em] text-slate-500">{title}</h3>{children}</section>;
}

export function TemplateTaskEditorModal({ task, tasks=[], durationDays, revisionToken, nextSequence, suggestedCode, onClose, onSaved, onDirtyChange }) {
  const [form,setForm]=useState(()=>asForm(task,nextSequence,suggestedCode)); const [errors,setErrors]=useState({}); const [requestError,setRequestError]=useState(""); const [saving,setSaving]=useState(false);
  const initial=useMemo(()=>JSON.stringify(asForm(task,nextSequence,suggestedCode)),[nextSequence,suggestedCode,task]); const dirty=JSON.stringify(form)!==initial;
  // Retired options stay visible only on a task that already uses them, so legacy data still reads truthfully.
  const phaseOptions=useMemo(()=>{
    const values=new Set([...APPROVED_PHASES,...tasks.map(item=>item.phase).filter(Boolean)].filter(value=>!LEGACY_PHASES.includes(value)));
    if(task?.phase)values.add(task.phase);
    return [...values].sort();
  },[task,tasks]);
  const categoryOptions=useMemo(()=>Array.from(new Set([...APPROVED_CATEGORIES,...tasks.map(item=>item.category).filter(Boolean)])).sort(),[tasks]);
  const legacyKind=Boolean(task?.task_kind&&TASK_KIND_LABELS[task.task_kind]&&task.task_kind!=="work");
  // Standard/Class A only applies to ordinary work; approval tasks and milestones keep no class.
  const nonWork=["approval_gate","milestone"].includes(form.task_kind);
  const preActivation=form.schedule_classification==="pre_activation";
  useEffect(()=>{onDirtyChange?.(dirty);return()=>onDirtyChange?.(false)},[dirty,onDirtyChange]);
  function change(name,value){setForm(current=>{const next={...current,[name]:value};if(name==="planned_start_day"&&next.planned_end_day==="")next.planned_end_day=value;next.duration_days=derivedDuration(next);return next});setErrors(current=>({...current,[name]:""}));setRequestError("");}
  function scheduleOnProjectDays(){setForm(current=>({...current,schedule_classification:"execution",phase:LEGACY_PHASES.includes(current.phase)?"":current.phase}));}
  function validate(){const next={};const sequence=Number(form.sequence_no),start=form.planned_start_day===""?null:Number(form.planned_start_day),end=form.planned_end_day===""?null:Number(form.planned_end_day);if(!form.code.trim())next.code="Task code is required.";if(!form.title.trim())next.title="Give the task a name.";if(!Number.isInteger(sequence)||sequence<1)next.sequence_no="Enter a positive sequence.";if(!preActivation){if(!Number.isInteger(start))next.planned_start_day="Enter the day it starts.";if(!Number.isInteger(end))next.planned_end_day="Enter the day it ends.";if(Number.isInteger(start)&&(start<1||start>durationDays))next.planned_start_day=`Use Day 1-${durationDays}.`;if(Number.isInteger(end)&&(end<1||end>durationDays))next.planned_end_day=`Use Day 1-${durationDays}.`;if(Number.isInteger(start)&&Number.isInteger(end)&&start>end)next.planned_end_day="End day cannot precede start day.";}setErrors(next);return !Object.keys(next).length;}
  async function submit(event){event.preventDefault();if(saving||!validate())return;setSaving(true);setRequestError("");const duration=preActivation?(form.duration_days===""?null:Number(form.duration_days)):Number(derivedDuration(form));try{await onSaved({code:form.code.trim(),sequence_no:Number(form.sequence_no),title:form.title.trim(),description:optional(form.description),schedule_classification:form.schedule_classification,planned_start_day:preActivation?null:Number(form.planned_start_day),planned_end_day:preActivation?null:Number(form.planned_end_day),phase:optional(form.phase),category:optional(form.category),applicability:form.applicability,task_class:nonWork?null:optional(form.task_class),task_kind:optional(form.task_kind),evidence_required:Boolean(form.evidence_required),duration_days:Number.isInteger(duration)?duration:null,revision_token:revisionToken},task)}catch(error){setRequestError(errorCopy(error));setSaving(false)}}
  function close(){if(!dirty||window.confirm("Discard unsaved task changes?"))onClose();}
  return <Modal title={task?"Edit task":"Add task"} subtitle="Changes apply to projects created after this version is published." onClose={close} className="sm:max-w-4xl"><form className="grid gap-5" onSubmit={submit} noValidate>
    {requestError&&<Alert tone="danger" role="alert"><AlertTriangle size={18}/><div><strong>Task was not saved</strong><span className="mt-1 block">{requestError}</span></div></Alert>}
    <Section title="What">
      <Field label="Task name" error={errors.title}><Input aria-label="Task name" value={form.title} onChange={e=>change("title",e.target.value)}/></Field>
      <Field label="Instructions" hint="What the team needs to know to do this task."><Textarea aria-label="Task instructions" value={form.description} onChange={e=>change("description",e.target.value)}/></Field>
    </Section>
    <Section title="When">
      {preActivation&&<Alert tone="info"><CalendarDays size={18}/><div className="flex-1"><strong>This task happens before the project starts</strong><span className="mt-1 block">It is an older pre-activation task with no project days.</span></div><Button size="sm" variant="secondary" onClick={scheduleOnProjectDays}>Schedule it on project days</Button></Alert>}
      <div className="grid gap-4 sm:grid-cols-3">
        <Field label="Starts on day" error={errors.planned_start_day}><Input aria-label="Starts on day" type="number" min="1" max={durationDays} disabled={preActivation} value={form.planned_start_day} onChange={e=>change("planned_start_day",e.target.value)}/></Field>
        <Field label="Ends on day" error={errors.planned_end_day}><Input aria-label="Ends on day" type="number" min="1" max={durationDays} disabled={preActivation} value={form.planned_end_day} onChange={e=>change("planned_end_day",e.target.value)}/></Field>
        <div className="grid gap-2 text-sm font-bold text-slate-700"><span>Duration</span><p className="flex min-h-11 items-center rounded-xl border border-slate-200 bg-white px-3 text-slate-950" aria-label="Task duration">{form.duration_days?`${form.duration_days} day${Number(form.duration_days)===1?"":"s"}`:"Set the days"}</p></div>
        <Field label="Phase"><Select aria-label="Phase" value={form.phase} onChange={e=>change("phase",e.target.value)}><option value="">Select phase</option>{phaseOptions.map(value=><option key={value}>{value}</option>)}</Select></Field>
        <Field label="Category"><Select aria-label="Category" value={form.category} onChange={e=>change("category",e.target.value)}><option value="">Select category</option>{categoryOptions.map(value=><option key={value}>{value}</option>)}</Select></Field>
      </div>
      <TemplateChoiceGroup label="Required on every project?" name="task-applicability" value={form.applicability} options={APPLICABILITY_OPTIONS} onChange={value=>change("applicability",value)}/>
    </Section>
    <Section title="Task class">
      {nonWork
        ? <p className="text-sm font-semibold text-slate-600">Not used for a {TASK_KIND_LABELS[form.task_kind].toLowerCase()}. Its approval steps are fixed.</p>
        : <TemplateChoiceGroup label="Task class" name="task-class" value={form.task_class||"standard"} options={TASK_CLASS_OPTIONS} onChange={value=>change("task_class",value)}/>}
      <p className="text-xs font-semibold text-slate-500">Who checks and approves follows from the class and from who actually does the work on the project.</p>
    </Section>
    <Section title="Proof">
      <label className="flex items-start gap-3 rounded-xl border border-slate-200 bg-white p-3 text-sm"><input aria-label="Proof required to finish" type="checkbox" checked={form.evidence_required} onChange={e=>change("evidence_required",e.target.checked)} className="mt-1 size-4 accent-blue-700"/><span><strong className="block text-slate-950">Proof required to finish</strong><span className="mt-1 block text-xs font-semibold text-slate-600">The person doing the work must attach a photo or document before submitting it for checking.</span></span></label>
    </Section>
    <details className="rounded-2xl border border-slate-200 bg-white p-4 sm:p-5">
      <summary className="cursor-pointer text-sm font-black text-slate-700">Advanced</summary>
      <div className="mt-4 grid gap-4 sm:grid-cols-2">
        <Field label="Task code" error={errors.code} hint="Filled in automatically. Must be unique in this template."><Input aria-label="Task code" value={form.code} onChange={e=>change("code",e.target.value)}/></Field>
        {legacyKind&&<Field label="Task type" hint="Older task type. Choose ordinary work to use Standard / Class A."><Select aria-label="Task type" value={form.task_kind} onChange={e=>change("task_kind",e.target.value)}><option value="">Ordinary work</option><option value={task.task_kind}>{TASK_KIND_LABELS[task.task_kind]}</option></Select></Field>}
      </div>
    </details>
    <footer className="sticky -bottom-4 -mx-4 flex flex-col-reverse gap-2 border-t border-slate-100 bg-white/95 px-4 py-4 backdrop-blur sm:-bottom-6 sm:-mx-6 sm:flex-row sm:justify-end sm:px-6"><Button variant="secondary" className="w-full sm:w-auto" onClick={close}>Cancel</Button><Button type="submit" loading={saving} className="w-full sm:w-auto"><Save size={17}/>{task?"Save task":"Add task"}</Button></footer>
  </form></Modal>;
}
