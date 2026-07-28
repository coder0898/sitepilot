import { AlertCircle, CheckCircle2, ChevronRight, Clock3, RefreshCw, Rocket, ShieldCheck, TriangleAlert } from "lucide-react";
import { useMemo, useState } from "react";
import { templatesApi } from "../../../api/templatesApi";
import { Alert, Button, Field, Modal, Pill, Textarea } from "../../../components/ui";

function responseMessage(error) {
  const detail = error?.details?.detail;
  if (detail?.code === "stale_template_version") return "This draft changed in another session. Refresh the draft and validate again.";
  if (detail?.code === "template_validation_failed") return detail.message || "The draft contains blocking validation errors.";
  if (typeof detail?.message === "string") return detail.message;
  if (typeof error?.message === "string") return error.message;
  return "The request could not be completed.";
}

function issueTarget(issue) {
  const value = `${issue?.group || ""} ${issue?.entity_type || ""}`.toLowerCase();
  if (value.includes("depend")) return "dependencies";
  if (value.includes("gate") || value.includes("mapping")) return "gates";
  return "tasks";
}

function targetLabel(target) {
  if (target === "dependencies") return "Dependencies";
  if (target === "gates") return "External Gates";
  return "Tasks";
}

function PublishModal({ busy, error, onClose, onPublish }) {
  const [changeNote, setChangeNote] = useState("");
  const [localError, setLocalError] = useState("");
  function submit() {
    const note = changeNote.trim();
    if (!note) {
      setLocalError("A change note is required before publication.");
      return;
    }
    setLocalError("");
    onPublish(note);
  }
  return <Modal title="Publish template version?" subtitle="Publication is permanent for this version." onClose={onClose} className="sm:max-w-xl">
    <div className="grid gap-5">
      <Alert tone="warning"><TriangleAlert size={18}/><div><strong>This version will become immutable</strong><span className="mt-1 block">Tasks, dependencies and external gates cannot be edited after publication. Future changes require a new draft version.</span></div></Alert>
      {(error || localError) && <Alert tone="danger" role="alert"><AlertCircle size={18}/><div><strong>Publication did not complete</strong><span className="mt-1 block">{localError || responseMessage(error)}</span></div></Alert>}
      <Field label="Publication change note" hint="Describe the approved change represented by this version.">
        <Textarea aria-label="Publication change note" value={changeNote} onChange={event => setChangeNote(event.target.value)} placeholder="Approved sequencing, task and readiness-gate updates."/>
      </Field>
      <div className="flex flex-col-reverse gap-2 sm:flex-row sm:justify-end">
        <Button variant="secondary" onClick={onClose} disabled={busy}>Cancel</Button>
        <Button className="w-full sm:w-auto" loading={busy} onClick={submit}><Rocket size={16}/> Publish immutable version</Button>
      </div>
    </div>
  </Modal>;
}

export function TemplateValidationPublishPanel({ summary, onNavigate, onRefresh, onPublished }) {
  const [validation, setValidation] = useState(null);
  const [validationState, setValidationState] = useState("idle");
  const [validationError, setValidationError] = useState(null);
  const [publishOpen, setPublishOpen] = useState(false);
  const [publishState, setPublishState] = useState("idle");
  const [publishError, setPublishError] = useState(null);

  const issuesByTarget = useMemo(() => {
    const groups = { tasks: [], dependencies: [], gates: [] };
    (validation?.issues || []).forEach(issue => groups[issueTarget(issue)].push(issue));
    return groups;
  }, [validation]);

  const stale = validation && validation.draft_revision !== summary.revision_token;
  const canPublish = Boolean(validation?.can_publish && !stale && validationState === "passed" && publishState !== "running");

  async function validate() {
    if (validationState === "running") return;
    setValidationState("running");
    setValidationError(null);
    setPublishError(null);
    try {
      const result = await templatesApi.validateVersion(summary.version_id);
      setValidation(result);
      setValidationState(result.can_publish ? "passed" : "failed");
    } catch (error) {
      setValidationError(error);
      setValidationState(error?.details?.detail?.code === "stale_template_version" ? "stale" : "failed");
    }
  }

  async function publish(changeNote) {
    if (!canPublish || publishState === "running") return;
    setPublishState("running");
    setPublishError(null);
    try {
      const result = await templatesApi.publishVersion(summary.version_id, {
        revision_token: summary.revision_token,
        change_note: changeNote,
      });
      setPublishState("success");
      setPublishOpen(false);
      onPublished(result);
    } catch (error) {
      setPublishError(error);
      setPublishState(error?.details?.detail?.code === "stale_template_version" ? "stale" : "failed");
    }
  }

  return <section className="grid gap-4" data-testid="template-validation-publish">
    <div className="flex flex-col gap-4 rounded-2xl border border-emerald-200 bg-emerald-50 p-4 sm:flex-row sm:items-center sm:justify-between">
      <div className="flex items-start gap-3"><ShieldCheck className="mt-0.5 shrink-0 text-emerald-700" size={20}/><div><strong className="text-emerald-950">Validate and publish</strong><p className="mt-1 text-xs font-semibold leading-5 text-emerald-800">Run authoritative backend validation before making this version immutable.</p></div></div>
      <Button className="w-full sm:w-auto" variant="secondary" loading={validationState === "running"} onClick={validate}><RefreshCw size={16}/> Validate Draft</Button>
    </div>

    {validationState === "idle" && <Alert tone="info"><Clock3 size={18}/><span>Validation has not been run for the current draft revision.</span></Alert>}
    {validationState === "running" && <Alert tone="info"><RefreshCw className="animate-spin" size={18}/><span>Validation is running against persisted draft content.</span></Alert>}
    {validationError && <Alert tone="danger" role="alert"><AlertCircle size={18}/><div><strong>Validation failed to run</strong><span className="mt-1 block">{responseMessage(validationError)}</span></div></Alert>}
    {stale && <Alert tone="warning" role="alert" className="items-center"><TriangleAlert size={18}/><div className="flex-1"><strong>Validation result is stale</strong><span className="mt-1 block">The draft revision changed after validation. Refresh and validate again.</span></div><Button size="sm" variant="secondary" onClick={onRefresh}>Refresh draft</Button></Alert>}

    {validation && <>
      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4" aria-label="Validation summary">
        <div className="rounded-2xl border border-slate-200 bg-white p-4"><small className="font-bold text-slate-500">Blocking errors</small><strong className="mt-1 block text-2xl text-red-700">{validation.severity_counts.blocking}</strong></div>
        <div className="rounded-2xl border border-slate-200 bg-white p-4"><small className="font-bold text-slate-500">Warnings</small><strong className="mt-1 block text-2xl text-amber-700">{validation.severity_counts.warnings}</strong></div>
        <div className="rounded-2xl border border-slate-200 bg-white p-4"><small className="font-bold text-slate-500">Tasks</small><strong className="mt-1 block text-2xl text-slate-950">{validation.entity_counts.tasks}</strong></div>
        <div className="rounded-2xl border border-slate-200 bg-white p-4"><small className="font-bold text-slate-500">Dependencies / Gates</small><strong className="mt-1 block text-2xl text-slate-950">{validation.entity_counts.dependencies} / {validation.entity_counts.gates}</strong></div>
      </div>

      <Alert tone={validation.can_publish && !stale ? "success" : "danger"} role="status">
        {validation.can_publish && !stale ? <CheckCircle2 size={19}/> : <TriangleAlert size={19}/>}<div><strong>{validation.can_publish && !stale ? "Validation passed" : "Validation has blocking issues"}</strong><span className="mt-1 block">Validated at {new Date(validation.validated_at).toLocaleString()} · Revision {String(validation.draft_revision).slice(-10)}</span></div>
      </Alert>

      {(validation.issues || []).length > 0 && <div className="grid gap-3">
        {Object.entries(issuesByTarget).filter(([, issues]) => issues.length).map(([target, issues]) => <section key={target} className="rounded-2xl border border-slate-200 bg-white p-4">
          <button className="flex w-full items-center justify-between gap-3 text-left" onClick={() => onNavigate(target)} aria-label={`Open ${targetLabel(target)} issues`}>
            <span><strong className="text-sm text-slate-950">{targetLabel(target)}</strong><small className="ml-2 text-slate-500">{issues.length} issue{issues.length === 1 ? "" : "s"}</small></span><ChevronRight size={18}/>
          </button>
          <div className="mt-3 grid gap-2">{issues.map((issue, index) => <button key={`${issue.code}-${issue.entity_id || index}`} onClick={() => onNavigate(target)} className="rounded-xl border border-slate-100 bg-slate-50 p-3 text-left hover:border-blue-200" aria-label={`Open issue ${issue.code}`}>
            <div className="flex flex-wrap items-center gap-2"><Pill tone={issue.severity === "error" ? "red" : "orange"}>{issue.severity}</Pill>{issue.blocking && <Pill tone="red">Blocking</Pill>}<span className="font-mono text-[10px] font-black text-slate-500">{issue.code}</span></div><p className="mt-2 text-xs font-semibold leading-5 text-slate-700">{issue.message}</p>
          </button>)}</div>
        </section>)}
      </div>}
    </>}

    {publishError && !publishOpen && <Alert tone="danger" role="alert" className="items-center"><AlertCircle size={18}/><div className="flex-1"><strong>{publishState === "stale" ? "Draft is stale" : "Publication failed or rolled back"}</strong><span className="mt-1 block">{responseMessage(publishError)}</span></div><Button size="sm" variant="secondary" onClick={onRefresh}>Refresh draft</Button></Alert>}

    <footer className="rounded-2xl border border-slate-200 bg-white p-4 shadow-[0_12px_36px_rgba(15,23,42,.06)]">
      <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between"><div><strong className="text-sm text-slate-950">Publication readiness</strong><p className="mt-1 text-xs font-semibold text-slate-500">Publish is enabled only after the current revision passes with zero blocking errors.</p></div><Button className="w-full sm:w-auto" disabled={!canPublish} onClick={() => { setPublishError(null); setPublishOpen(true); }}><Rocket size={16}/> Publish Version</Button></div>
    </footer>

    {publishOpen && <PublishModal busy={publishState === "running"} error={publishError} onClose={() => { if (publishState !== "running") setPublishOpen(false); }} onPublish={publish}/>} 
  </section>;
}
