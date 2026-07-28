import { AlertTriangle, Save } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { Alert, Button, Field, Input, Modal, Select, Textarea } from "../../../components/ui";

const emptyDependency = {
  predecessor_task_id: "",
  successor_task_id: "",
  dependency_type: "finish_to_start",
  blocking: true,
  rule_text: "",
  sequence_no: "",
};

function dependencyErrorCopy(error) {
  const detail = error?.details?.detail;
  if (detail?.code === "stale_template_version") return "This draft changed in another session. Refresh it before retrying.";
  if (detail?.code === "template_dependency_cycle") return detail.message || "This relationship would create a dependency cycle.";
  if (detail?.code === "template_dependency_exists") return detail.message || "This dependency already exists.";
  if (detail?.code === "invalid_template_dependency") return detail.message || "The dependency is invalid.";
  return detail?.message || (typeof error?.message === "string" ? error.message : "The dependency could not be saved.");
}

function asForm(dependency, nextSequence) {
  if (!dependency) return { ...emptyDependency, sequence_no: nextSequence ?? "" };
  return {
    predecessor_task_id: dependency.predecessor_task_id || dependency.predecessor?.id || "",
    successor_task_id: dependency.successor_task_id || dependency.successor?.id || "",
    dependency_type: dependency.dependency_type || "finish_to_start",
    blocking: Boolean(dependency.blocking),
    rule_text: dependency.rule_text || "",
    sequence_no: dependency.sequence_no ?? nextSequence ?? "",
  };
}

export function TemplateDependencyEditorModal({ dependency, tasks, revisionToken, nextSequence, onClose, onSaved, onDirtyChange }) {
  const [form, setForm] = useState(() => asForm(dependency, nextSequence));
  const [errors, setErrors] = useState({});
  const [requestError, setRequestError] = useState("");
  const [saving, setSaving] = useState(false);
  const initial = useMemo(() => JSON.stringify(asForm(dependency, nextSequence)), [dependency, nextSequence]);
  const dirty = JSON.stringify(form) !== initial;

  useEffect(() => { onDirtyChange?.(dirty); return () => onDirtyChange?.(false); }, [dirty, onDirtyChange]);

  function change(name, value) {
    setForm(current => ({ ...current, [name]: value }));
    setErrors(current => ({ ...current, [name]: "", relationship: "" }));
    setRequestError("");
  }

  function validate() {
    const next = {};
    if (!form.predecessor_task_id) next.predecessor_task_id = "Select a predecessor task.";
    if (!form.successor_task_id) next.successor_task_id = "Select a successor task.";
    if (form.predecessor_task_id && form.predecessor_task_id === form.successor_task_id) next.relationship = "Predecessor and successor must be different tasks.";
    if (!form.rule_text.trim()) next.rule_text = "Rule text is required.";
    if (!Number.isInteger(Number(form.sequence_no)) || Number(form.sequence_no) < 1) next.sequence_no = "Enter a positive sequence.";
    setErrors(next);
    return Object.keys(next).length === 0;
  }

  async function submit(event) {
    event.preventDefault();
    if (saving || !validate()) return;
    setSaving(true); setRequestError("");
    const payload = {
      predecessor_task_id: form.predecessor_task_id,
      successor_task_id: form.successor_task_id,
      dependency_type: form.dependency_type,
      blocking: Boolean(form.blocking),
      rule_text: form.rule_text.trim(),
      sequence_no: Number(form.sequence_no),
      revision_token: revisionToken,
    };
    try { await onSaved(payload, dependency); }
    catch (error) { setRequestError(dependencyErrorCopy(error)); setSaving(false); }
  }

  function close() { if (!dirty || window.confirm("Discard unsaved dependency changes?")) onClose(); }

  return <Modal title={dependency ? "Edit draft dependency" : "Add draft dependency"} subtitle="Relationships may only use tasks from this draft version." onClose={close} className="sm:max-w-3xl">
    <form className="grid gap-6" onSubmit={submit} noValidate>
      {requestError && <Alert tone="danger" role="alert"><AlertTriangle size={18}/><div><strong>Dependency was not saved</strong><span className="mt-1 block">{requestError}</span></div></Alert>}
      {errors.relationship && <Alert tone="danger" role="alert"><AlertTriangle size={18}/><span>{errors.relationship}</span></Alert>}
      <section className="grid gap-4 sm:grid-cols-2">
        <Field label="Predecessor task" error={errors.predecessor_task_id}>
          <Select aria-label="Predecessor task" value={form.predecessor_task_id} onChange={event => change("predecessor_task_id", event.target.value)}>
            <option value="">Select predecessor</option>
            {tasks.map(task => <option key={task.id} value={task.id} disabled={task.id === form.successor_task_id}>{task.code} — {task.title}</option>)}
          </Select>
        </Field>
        <Field label="Successor task" error={errors.successor_task_id}>
          <Select aria-label="Successor task" value={form.successor_task_id} onChange={event => change("successor_task_id", event.target.value)}>
            <option value="">Select successor</option>
            {tasks.map(task => <option key={task.id} value={task.id} disabled={task.id === form.predecessor_task_id}>{task.code} — {task.title}</option>)}
          </Select>
        </Field>
        <Field label="Dependency type">
          <Select aria-label="Dependency type" value={form.dependency_type} onChange={event => change("dependency_type", event.target.value)}>
            <option value="finish_to_start">Finish-to-Start</option>
            <option value="start_to_start">Start-to-Start</option>
          </Select>
        </Field>
        <Field label="Sequence number" error={errors.sequence_no} hint="Generated from the current dependency order."><Input aria-label="Dependency sequence number" type="number" min="1" value={form.sequence_no} readOnly className="bg-slate-100"/></Field>
        <Field label="Rule text" error={errors.rule_text} className="sm:col-span-2"><Textarea aria-label="Dependency rule text" value={form.rule_text} onChange={event => change("rule_text", event.target.value)} placeholder="Explain when the successor may begin."/></Field>
        <label className="flex min-h-11 items-center gap-3 rounded-xl border border-slate-200 bg-white px-4 text-sm font-bold text-slate-700 shadow-sm sm:col-span-2"><input aria-label="Blocking dependency" type="checkbox" checked={form.blocking} onChange={event => change("blocking", event.target.checked)} className="size-4 accent-blue-700"/> Blocking relationship</label>
      </section>
      <footer className="sticky -bottom-4 -mx-4 flex flex-col-reverse gap-2 border-t border-slate-100 bg-white/95 px-4 py-4 backdrop-blur sm:-bottom-6 sm:-mx-6 sm:flex-row sm:justify-end sm:px-6">
        <Button variant="secondary" className="w-full sm:w-auto" onClick={close}>Cancel</Button>
        <Button type="submit" loading={saving} className="w-full sm:w-auto"><Save size={17}/>{dependency ? "Save dependency" : "Add relationship"}</Button>
      </footer>
    </form>
  </Modal>;
}
