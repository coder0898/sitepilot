import { ShieldCheck } from "lucide-react";
import { useState } from "react";
import { projectsApi } from "../../../api/projectsApi";
import { Alert, Button, Field, Input, Select } from "../../../components/ui";

const actionLabel = value => value.toLowerCase().replaceAll("_", " ").replace(/(^|\s)\S/g, match => match.toUpperCase());

// Mirrors change_status' guards in backend/app/routes/projects_v2.py:
// activate and archive are Admin-only, on-hold/complete are Admin or the
// project's own PM. Super Admin is deliberately absent - it cannot move a
// project's lifecycle at all.
const TRANSITIONS = {
  admin: { draft: ["active", "archived"], active: ["on_hold", "completed", "archived"], on_hold: ["active", "completed", "archived"], completed: ["archived"], archived: [] },
  project_manager: { active: ["on_hold", "completed"], on_hold: ["completed"] },
};

export function ProjectLifecyclePane({ project, user, onChanged, onDeleted }) {
  const transitions = TRANSITIONS[user.role]?.[project.status] || [];
  const canDelete = user.role === "admin" && project.status === "draft" && !project.template_version_id && project.memberships.length === 0;
  const isArchived = project.status === "archived";
  const canRestore = isArchived && user.role === "admin";
  const [target, setTarget] = useState(transitions[0] || "");
  const [reason, setReason] = useState("");
  const [confirmation, setConfirmation] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  async function restore(event) {
    event.preventDefault();
    setBusy(true);
    setError("");
    try {
      await projectsApi.restore(project.id, reason);
      setReason("");
      await onChanged();
    } catch (caught) {
      setError(caught.message);
    } finally {
      setBusy(false);
    }
  }

  async function changeStatus(event) {
    event.preventDefault();
    setBusy(true);
    setError("");
    try {
      await projectsApi.setStatus(project.id, target, reason);
      setReason("");
      await onChanged();
    } catch (caught) {
      setError(caught.message);
    } finally {
      setBusy(false);
    }
  }

  async function removeDraft() {
    setBusy(true);
    setError("");
    try {
      await projectsApi.remove(project.id, { confirmation, reason });
      await onDeleted();
    } catch (caught) {
      setError(caught.message);
      setBusy(false);
    }
  }

  // Explain the actual blocker. Saying "Admin only" to an Admin looking at
  // an archived project is both wrong and a dead end - archived is terminal
  // in change_status, which is a state problem, not a permission one.
  if (!transitions.length && !canDelete && !canRestore) {
    const message = isArchived
      ? "This project is archived. Only an Admin can restore it."
      : project.status === "completed"
        ? "This project is complete. Only an Admin can archive it from here."
        : "Your role cannot change this project's lifecycle state. Activating, archiving and deleting a project are Admin-only actions.";
    return <p className="rounded-2xl border border-slate-200 bg-white p-5 text-sm text-slate-500">{message}</p>;
  }

  const activationBlocked = target === "active" && project.status === "draft" && !project.setup.activation_ready;

  return <div className="grid gap-3">
    <section className="rounded-2xl border border-slate-200 bg-white p-4 sm:p-5">
      <div className="flex items-center gap-3">
        <span className="grid size-10 shrink-0 place-items-center rounded-xl bg-slate-100 text-slate-700"><ShieldCheck size={18} aria-hidden="true"/></span>
        <div>
          <h3 className="text-sm font-black text-slate-950">Project lifecycle</h3>
          <p className="text-xs text-slate-500">Every transition requires a reason and is retained in activity.</p>
        </div>
      </div>

      {error && <Alert tone="danger" className="mt-4">{error}</Alert>}

      {canRestore && <form onSubmit={restore} className="mt-4 grid gap-3">
        <p className="rounded-xl border border-amber-200 bg-amber-50 px-3 py-2.5 text-xs leading-5 text-amber-800">
          This project is archived. Restoring returns it to the state it held before archiving — a project
          that was active comes back <strong className="font-black">on hold</strong>, so work is never
          silently resumed.
        </p>
        <div className="grid gap-3 sm:grid-cols-[minmax(0,1fr)_auto] sm:items-end">
          <Field label="Reason for restoring">
            <Input value={reason} onChange={event => setReason(event.target.value)} minLength={4} required placeholder="Why is this project being restored?"/>
          </Field>
          <Button type="submit" loading={busy} disabled={reason.trim().length < 4}>Restore project</Button>
        </div>
      </form>}

      {transitions.length > 0 && <form onSubmit={changeStatus} className="mt-4 grid gap-3 sm:grid-cols-[180px_minmax(0,1fr)_auto] sm:items-end">
        <Field label="Move project to">
          <Select value={target} onChange={event => setTarget(event.target.value)}>
            {transitions.map(value => <option key={value} value={value}>{actionLabel(value)}</option>)}
          </Select>
        </Field>
        <Field label="Reason">
          <Input value={reason} onChange={event => setReason(event.target.value)} minLength={4} required placeholder="Operational reason for this change"/>
        </Field>
        <Button type="submit" loading={busy} disabled={activationBlocked}>Confirm</Button>
        {activationBlocked && <p className="text-xs font-bold text-amber-700 sm:col-span-3">
          Complete all four activation details first, and generate the task snapshot — activation also requires at least one included task.
        </p>}
      </form>}

      {canDelete && <div className="mt-5 border-t border-slate-100 pt-5">
        <h4 className="text-sm font-black text-rose-700">Delete unused draft</h4>
        <p className="mt-1 text-xs leading-5 text-slate-500">
          Only a draft with no team and no template can be permanently deleted. Type <strong>{project.code}</strong> and provide the reason.
        </p>
        <div className="mt-3 grid gap-3 sm:grid-cols-[180px_minmax(0,1fr)_auto] sm:items-end">
          <Field label="Project code"><Input value={confirmation} onChange={event => setConfirmation(event.target.value)} placeholder={project.code}/></Field>
          <Field label="Deletion reason"><Input value={reason} onChange={event => setReason(event.target.value)} minLength={4} placeholder="Why is this draft being removed?"/></Field>
          <Button variant="danger" disabled={confirmation !== project.code || reason.length < 4} loading={busy} onClick={removeDraft}>Delete draft</Button>
        </div>
      </div>}
    </section>
  </div>;
}
