import { useState } from "react";
import { projectsApi } from "../../../api/projectsApi";
import { Button, Field, Input, Modal, Select } from "../../../components/ui";

const initialForm = {
  predecessor_project_task_id: "",
  successor_project_task_id: "",
  dependency_type: "finish_to_start",
  rule_text: "",
  reason: "",
};

export function ProjectManualDependencyModal({ projectId, tasks = [], onClose, onCreated }) {
  const [form, setForm] = useState(initialForm);
  const [error, setError] = useState("");
  const [saving, setSaving] = useState(false);

  function update(field, value) {
    setForm(prev => ({ ...prev, [field]: value }));
  }

  async function submit(e) {
    e.preventDefault();
    if (!form.predecessor_project_task_id || !form.successor_project_task_id || !form.reason.trim()) {
      setError("Predecessor, successor and reason are required.");
      return;
    }
    setSaving(true);
    setError("");
    try {
      const created = await projectsApi.createDependency(projectId, {
        ...form,
        reason: form.reason.trim(),
        rule_text: form.rule_text.trim(),
      });
      onCreated?.(created);
      onClose();
    } catch (err) {
      setError(err?.message || "Unable to create dependency.");
    } finally {
      setSaving(false);
    }
  }

  const options = tasks.filter(t => t.included !== false);

  return (
    <Modal title="Create manual dependency" subtitle="Create a project-specific relationship without changing the published template." onClose={() => !saving && onClose()} className="sm:max-w-2xl">
      <form className="grid gap-4" onSubmit={submit}>
        <Field label="Predecessor task">
          <Select value={form.predecessor_project_task_id} onChange={e => update("predecessor_project_task_id", e.target.value)} disabled={saving}>
            <option value="">Select predecessor task</option>
            {options.map(t => <option key={t.id} value={t.id}>{t.original_code || t.code} - {t.title}</option>)}
          </Select>
        </Field>
        <Field label="Dependency type">
          <Select value={form.dependency_type} onChange={e => update("dependency_type", e.target.value)} disabled={saving}>
            <option value="finish_to_start">Finish to Start</option>
            <option value="start_to_start">Start to Start</option>
          </Select>
        </Field>
        <Field label="Successor task">
          <Select value={form.successor_project_task_id} onChange={e => update("successor_project_task_id", e.target.value)} disabled={saving}>
            <option value="">Select successor task</option>
            {options.map(t => <option key={t.id} value={t.id}>{t.original_code || t.code} - {t.title}</option>)}
          </Select>
        </Field>
        <Field label="Rule">
          <Input value={form.rule_text} onChange={e => update("rule_text", e.target.value)} disabled={saving}/>
        </Field>
        <Field label="Reason" error={!form.reason.trim() && error ? "Reason required." : ""}>
          <Input value={form.reason} onChange={e => update("reason", e.target.value)} disabled={saving}/>
        </Field>
        {error && <p className="text-sm font-bold text-rose-700">{error}</p>}
        <Button type="submit" loading={saving}>Create</Button>
      </form>
    </Modal>
  );
}
