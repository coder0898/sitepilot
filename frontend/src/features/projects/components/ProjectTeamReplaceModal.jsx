
import { useMemo, useState } from "react";
import { Button, Field, Input, Modal, Select } from "../../../components/ui";
import { projectsApi } from "../../../api/projectsApi";

export function ProjectTeamReplaceModal({ project, role, references, onClose, onChanged }) {
  const [userId, setUserId] = useState("");
  const [reason, setReason] = useState("");
  const [saving, setSaving] = useState(false);

  const users = useMemo(() => role === "project_manager" ? references.project_managers : references.supervisors, [role, references]);

  async function submit(e) {
    e.preventDefault();
    setSaving(true);
    try {
      await projectsApi.updateTeam(project.id, {
        project_manager_id: role === "project_manager" ? userId : undefined,
        supervisor_id: role === "site_supervisor" ? userId : undefined,
        reason
      });
      await onChanged();
      onClose();
    } finally {
      setSaving(false);
    }
  }

  return <Modal title={`Change ${role === "project_manager" ? "Project Manager" : "Supervisor"}`} onClose={onClose}>
    <form onSubmit={submit} className="grid gap-4">
      <Field label="Select active user">
        <Select value={userId} onChange={e => setUserId(e.target.value)} required>
          <option value="">Select user</option>
          {users.map(u => <option key={u.employee_id} value={u.employee_id}>{u.name} - {u.designation}</option>)}
        </Select>
      </Field>
      <Field label="Reason">
        <Input value={reason} onChange={e => setReason(e.target.value)} required placeholder="Replacement reason"/>
      </Field>
      <Button loading={saving}>Replace</Button>
    </form>
  </Modal>;
}
