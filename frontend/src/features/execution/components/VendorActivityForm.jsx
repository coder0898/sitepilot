import { useState } from "react";
import { vendorAssignmentApi } from "../../../api/vendorAssignmentApi";
import { Button, Field, Input, Select, Textarea } from "../../../components/ui";

const EVENT_TYPES = ["presence", "delay", "rework", "incident"];

function triggerDownload(blob, filename) {
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(url);
}

// U3: vendor-attributable activity/incident capture (R5). Evidence is
// optional for every event_type, including 'incident' - the backend never
// requires it. `responsibility_decision` is free text, used mainly for
// 'delay' events per the plan, but not restricted to that type.
export function VendorActivityForm({ projectId, task, assignment, canManage = true, onChanged }) {
  const [eventType, setEventType] = useState("presence");
  const [description, setDescription] = useState("");
  const [responsibilityDecision, setResponsibilityDecision] = useState("");
  const [file, setFile] = useState(null);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState("");

  async function submit(event) {
    event.preventDefault();
    setSubmitting(true);
    setError("");
    try {
      const formData = new FormData();
      formData.append("event_type", eventType);
      formData.append("description", description.trim());
      if (responsibilityDecision.trim()) formData.append("responsibility_decision", responsibilityDecision.trim());
      if (file) formData.append("evidence", file);
      await vendorAssignmentApi.logActivity(projectId, task.id, assignment.id, formData);
      setDescription("");
      setResponsibilityDecision("");
      setFile(null);
      await onChanged();
    } catch (caught) {
      setError(caught?.message || "This activity could not be logged.");
    } finally {
      setSubmitting(false);
    }
  }

  async function download(evidenceFile) {
    try {
      const { blob, filename } = await vendorAssignmentApi.downloadActivityEvidence(projectId, task.id, assignment.id, evidenceFile.file_id);
      triggerDownload(blob, filename || evidenceFile.original_filename);
    } catch (caught) {
      setError(caught?.message || "This evidence file could not be downloaded.");
    }
  }

  return <div className="mt-3 border-t border-slate-100 pt-3">
    <h5 className="text-[10px] font-black uppercase tracking-wide text-slate-400">Activity / incident log</h5>
    {assignment.activity_events.length > 0 && <div className="mt-2 grid gap-2">{assignment.activity_events.map(activityEvent => <article key={activityEvent.id} className="rounded-lg bg-slate-50 p-2 text-xs">
      <div className="flex flex-wrap items-center justify-between gap-2"><strong className="capitalize text-slate-800">{activityEvent.event_type}</strong><time className="text-slate-400">{new Date(activityEvent.created_at).toLocaleString("en-GB")}</time></div>
      <p className="mt-1 text-slate-600">{activityEvent.description}</p>
      {activityEvent.responsibility_decision && <p className="mt-1 font-bold text-amber-700">{activityEvent.responsibility_decision}</p>}
      {activityEvent.evidence.length > 0 && <div className="mt-1 flex flex-wrap gap-2">{activityEvent.evidence.map(file => <button key={file.id} type="button" onClick={() => download(file)} className="rounded-md bg-blue-100 px-2 py-1 font-bold text-blue-700 hover:bg-blue-200">{file.original_filename}</button>)}</div>}
    </article>)}</div>}

    {canManage && <form className="mt-2 grid gap-2" onSubmit={submit}>
      <div className="grid gap-2 sm:grid-cols-2">
        <Field label="Event type"><Select value={eventType} onChange={event => setEventType(event.target.value)}>{EVENT_TYPES.map(value => <option key={value} value={value}>{value}</option>)}</Select></Field>
        <Field label="Responsibility decision (optional)"><Input value={responsibilityDecision} onChange={event => setResponsibilityDecision(event.target.value)} placeholder="e.g. Vendor responsible"/></Field>
      </div>
      <Field label="Description"><Textarea className="min-h-16" value={description} onChange={event => setDescription(event.target.value)} placeholder="What happened?" required/></Field>
      {/* capture="environment" biases the mobile OS picker to the rear
          camera - PDFs still reachable via the same picker's "Files"
          option. */}
      <label className="grid gap-1 text-xs font-bold text-slate-700">Evidence photo or PDF (optional)<input className="w-full cursor-pointer rounded-lg border border-slate-200 bg-white text-xs font-normal text-slate-600 file:mr-3 file:border-0 file:bg-slate-700 file:px-2 file:py-1.5 file:font-bold file:text-white hover:file:bg-slate-800" type="file" accept="image/jpeg,image/png,image/webp,application/pdf" capture="environment" onChange={event => setFile(event.target.files?.[0] || null)}/></label>
      {error && <p className="text-xs font-bold text-rose-700">{error}</p>}
      <Button type="submit" size="sm" loading={submitting} disabled={!description.trim()}>Log activity</Button>
    </form>}
  </div>;
}
