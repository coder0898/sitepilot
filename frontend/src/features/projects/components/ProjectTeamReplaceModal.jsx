
import { useMemo, useState } from "react";
import { Button, Field, Input, Modal, Select } from "../../../components/ui";
import { projectsApi } from "../../../api/projectsApi";

// U6: PM/Supervisor replacement is now a two-step request/approval flow
// (BR-007), not an immediate change - submitting here creates a `pending`
// project_role_changes record instead of swapping the membership right
// away. A second authorized actor (Admin for PM, PM/Admin for Supervisor)
// must separately approve it before the previous membership actually ends
// and the replacement starts. This is an intentional behavior change from
// the prior immediate-effect UX - flagged per the plan's risk note.
export function ProjectTeamReplaceModal({ project, role, references, onClose, onChanged }) {
  const [employeeId, setEmployeeId] = useState("");
  const [reason, setReason] = useState("");
  const [saving, setSaving] = useState(false);
  const [requested, setRequested] = useState(null);
  const [error, setError] = useState(null);

  const users = useMemo(() => role === "project_manager" ? references.project_managers : references.supervisors, [role, references]);

  async function submit(e) {
    e.preventDefault();
    setSaving(true);
    setError(null);
    try {
      const change = await projectsApi.requestRoleChange(project.id, {
        role_type: role,
        replacement_employee_id: employeeId,
        reason
      });
      setRequested(change);
      await onChanged();
    } catch (err) {
      setError(err?.message || "Could not submit the role change request.");
    } finally {
      setSaving(false);
    }
  }

  const roleLabel = role === "project_manager" ? "Project Manager" : "Supervisor";

  if (requested) {
    return <Modal title={`${roleLabel} replacement requested`} onClose={onClose}>
      <div className="grid gap-4">
        <p>
          A replacement request for the {roleLabel} has been submitted and is <strong>pending approval</strong>.
          The current {roleLabel} remains accountable until an authorized approver decides this request.
        </p>
        <Button onClick={onClose}>Close</Button>
      </div>
    </Modal>;
  }

  return <Modal title={`Request ${roleLabel} replacement`} onClose={onClose}>
    <form onSubmit={submit} className="grid gap-4">
      <p className="text-sm text-slate-500">
        This submits a replacement request. It takes effect only once a separate authorized actor approves it -
        the current {roleLabel} stays accountable until then.
      </p>
      <Field label="Select active user">
        <Select value={employeeId} onChange={e => setEmployeeId(e.target.value)} required>
          <option value="">Select user</option>
          {users.map(u => <option key={u.employee_id} value={u.employee_id}>{u.name} - {u.designation}</option>)}
        </Select>
      </Field>
      <Field label="Reason">
        <Input value={reason} onChange={e => setReason(e.target.value)} required placeholder="Replacement reason"/>
      </Field>
      {error && <p className="text-sm font-bold text-rose-700">{error}</p>}
      <Button loading={saving}>Request replacement</Button>
    </form>
  </Modal>;
}
