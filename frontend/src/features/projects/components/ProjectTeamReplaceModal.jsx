
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
//
// Two request modes, both going through the same audited flow:
// - "replacement": names a successor now - approval swaps them in atomically.
// - "vacate": for when the current holder is leaving (e.g. offboarding) with
//   nobody lined up yet - approval just ends them, leaving the role "Not
//   assigned" until a later Add-team-member/Change request fills it. Only
//   offered when someone currently holds the role (hasCurrentHolder).
export function ProjectTeamReplaceModal({ project, role, references, hasCurrentHolder, onClose, onChanged }) {
  const [mode, setMode] = useState("replacement");
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
      const payload = mode === "vacate"
        ? { role_type: role, change_type: "vacate", reason }
        : { role_type: role, change_type: "replacement", replacement_employee_id: employeeId, reason };
      const change = await projectsApi.requestRoleChange(project.id, payload);
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
    return <Modal title={mode === "vacate" ? `${roleLabel} vacate requested` : `${roleLabel} replacement requested`} onClose={onClose}>
      <div className="grid gap-4">
        <p>
          {mode === "vacate"
            ? <>A request to vacate the {roleLabel} role has been submitted and is <strong>pending approval</strong>. Once approved, this project has no {roleLabel} until someone is assigned - the current {roleLabel} stays accountable until then.</>
            : <>A replacement request for the {roleLabel} has been submitted and is <strong>pending approval</strong>. The current {roleLabel} remains accountable until an authorized approver decides this request.</>}
        </p>
        <Button onClick={onClose}>Close</Button>
      </div>
    </Modal>;
  }

  return <Modal title={mode === "vacate" ? `Request to vacate ${roleLabel}` : `Request ${roleLabel} replacement`} onClose={onClose}>
    <form onSubmit={submit} className="grid gap-4">
      {hasCurrentHolder && <div className="flex gap-2 rounded-xl border border-slate-200 bg-slate-50 p-1">
        <button type="button" onClick={() => setMode("replacement")} className={`flex-1 rounded-lg px-3 py-2 text-sm font-bold transition ${mode === "replacement" ? "bg-white text-slate-950 shadow-sm" : "text-slate-500 hover:text-slate-800"}`}>Name a replacement</button>
        <button type="button" onClick={() => setMode("vacate")} className={`flex-1 rounded-lg px-3 py-2 text-sm font-bold transition ${mode === "vacate" ? "bg-white text-slate-950 shadow-sm" : "text-slate-500 hover:text-slate-800"}`}>Vacate now, fill later</button>
      </div>}

      {mode === "vacate" ? (
        <p className="text-sm text-slate-500">
          This submits a request to end the current {roleLabel}'s assignment with <strong>no replacement named yet</strong>.
          Once approved, the project shows "Not assigned" for {roleLabel} until you add or request someone new - use this
          when the person is leaving (e.g. offboarding) and nobody is lined up to take over immediately.
        </p>
      ) : (
        <p className="text-sm text-slate-500">
          This submits a replacement request. It takes effect only once a separate authorized actor approves it -
          the current {roleLabel} stays accountable until then.
        </p>
      )}

      {mode === "replacement" && <Field label="Select active user">
        <Select value={employeeId} onChange={e => setEmployeeId(e.target.value)} required>
          <option value="">Select user</option>
          {users.map(u => <option key={u.employee_id} value={u.employee_id}>{u.name} - {u.designation}</option>)}
        </Select>
      </Field>}
      <Field label="Reason">
        <Input value={reason} onChange={e => setReason(e.target.value)} required placeholder={mode === "vacate" ? "Why is this role being vacated?" : "Replacement reason"}/>
      </Field>
      {error && <p className="text-sm font-bold text-rose-700">{error}</p>}
      <Button type="submit" loading={saving} variant={mode === "vacate" ? "danger" : "primary"}>{mode === "vacate" ? "Request vacate" : "Request replacement"}</Button>
    </form>
  </Modal>;
}
