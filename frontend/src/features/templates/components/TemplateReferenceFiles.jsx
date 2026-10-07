import { FileText, Trash2, Upload } from "lucide-react";
import { useState } from "react";
import { templatesApi } from "../../../api/templatesApi";
import { Button, Field, Input } from "../../../components/ui";
import { triggerDownload } from "../../execution/components/ReferenceMaterial";

// Mirrors the server's rules (template_reference_files.py), which still re-check every upload.
const ACCEPTED_EXTENSIONS = [".pdf", ".jpg", ".jpeg", ".png", ".webp", ".docx", ".xlsx"];
const MAX_SIZE_BYTES = 10 * 1024 * 1024;
const TYPE_MESSAGE = "Reference files must be PDF, JPG, PNG, WebP, DOCX or XLSX.";

function fileProblem(file) {
  const name = file.name.toLowerCase();
  if (!ACCEPTED_EXTENSIONS.some(extension => name.endsWith(extension))) return TYPE_MESSAGE;
  if (file.size === 0) return "The file is empty.";
  if (file.size > MAX_SIZE_BYTES) return "Reference files must be 10 MB or smaller.";
  return "";
}

function apiMessage(error, fallback) {
  const detail = error?.details?.detail;
  if (detail?.code === "stale_template_version") return "This draft changed in another session. Refresh it before trying again.";
  return (typeof detail === "string" && detail) || detail?.message || error?.message || fallback;
}

/**
 * Admin reference material on a saved draft task or approval: files the person
 * doing the work can read - never the evidence they submit. Each upload or
 * removal is its own draft change, so the new revision token is handed back.
 */
export function TemplateReferenceFiles({ versionId, kind, ownerId, files: initialFiles = [], revisionToken, onChanged }) {
  const [files, setFiles] = useState(initialFiles);
  const [file, setFile] = useState(null);
  const [description, setDescription] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [inputKey, setInputKey] = useState(0);

  function choose(chosen) {
    setError("");
    if (!chosen) { setFile(null); return; }
    const problem = fileProblem(chosen);
    setError(problem);
    setFile(problem ? null : chosen);
  }

  async function upload() {
    if (!file || busy) return;
    setBusy(true); setError("");
    try {
      const response = await templatesApi.addReferenceFile(versionId, kind, ownerId, { file, description: description.trim(), revisionToken });
      setFiles(current => [...current, response.reference]);
      setFile(null); setDescription(""); setInputKey(key => key + 1);
      onChanged?.(response.revision_token);
    } catch (caught) {
      setError(apiMessage(caught, "The file could not be uploaded."));
    } finally {
      setBusy(false);
    }
  }

  async function remove(reference) {
    if (busy) return;
    setBusy(true); setError("");
    try {
      const response = await templatesApi.removeReferenceFile(versionId, kind, ownerId, reference.id, revisionToken);
      setFiles(current => current.filter(item => item.id !== reference.id));
      onChanged?.(response.revision_token);
    } catch (caught) {
      setError(apiMessage(caught, "The file could not be removed."));
    } finally {
      setBusy(false);
    }
  }

  async function download(reference) {
    setError("");
    try {
      const { blob, filename } = await templatesApi.downloadReferenceFile(versionId, kind, ownerId, reference.id);
      triggerDownload(blob, filename || reference.filename);
    } catch (caught) {
      setError(apiMessage(caught, "The file could not be downloaded."));
    }
  }

  return <div role="group" aria-label="Reference material" className="grid gap-3">
    <p className="text-xs font-semibold text-slate-600">Files the person doing the work can read, such as an approved spec or a form. This is not their proof of work.</p>
    {files.length > 0 ? <ul className="grid gap-2">{files.map(reference => <li key={reference.id} className="flex items-start justify-between gap-2 rounded-xl border border-slate-200 bg-white px-3 py-2">
      <button type="button" className="flex min-w-0 items-start gap-2 text-left" onClick={() => download(reference)} aria-label={`Download ${reference.filename}`}>
        <FileText size={16} className="mt-0.5 shrink-0 text-blue-700"/>
        <span className="min-w-0"><span className="block truncate text-sm font-bold text-blue-700">{reference.filename}</span>{reference.description && <span className="block text-xs font-semibold text-slate-600">{reference.description}</span>}</span>
      </button>
      <Button size="icon" variant="ghost" aria-label={`Remove ${reference.filename}`} disabled={busy} onClick={() => remove(reference)}><Trash2 size={15}/></Button>
    </li>)}</ul> : <p className="text-sm font-semibold text-slate-500">No reference files yet.</p>}
    <div className="grid gap-3 sm:grid-cols-[1fr_1fr_auto] sm:items-end">
      <Field label="Reference file" hint="PDF, JPG, PNG, WebP, DOCX or XLSX, up to 10 MB.">
        <input key={inputKey} aria-label="Reference file" type="file" accept={ACCEPTED_EXTENSIONS.join(",")} onChange={event => choose(event.target.files?.[0] || null)} className="text-sm"/>
      </Field>
      <Field label="File description (optional)"><Input aria-label="File description (optional)" value={description} maxLength={500} onChange={event => setDescription(event.target.value)}/></Field>
      <Button type="button" variant="secondary" disabled={!file || busy} loading={busy} onClick={upload}><Upload size={15}/> Upload</Button>
    </div>
    {error && <p role="alert" className="text-xs font-bold text-rose-700">{error}</p>}
  </div>;
}
