import { useEffect, useState } from "react";
import { UserPlus, UserRoundCheck } from "lucide-react";
import { taskExecutionApi } from "../../../api/taskExecutionApi";
import { Button, Field, Pill, Select, Textarea } from "../../../components/ui";

// U13: who is chasing this external approval.
//
// Delegating is Admin's act, because owning the approval is Admin's. The
// delegate gets to record that it was submitted and nothing more - approving
// and rejecting stay with Admin, and the server enforces that regardless of
// what this panel offers.
//
// Everyone on the project can read this list. "Who is chasing the landlord"
// is exactly what a PM watching their handover date needs to know, and
// hiding it behind the authority to delegate would be backwards.

export function canDelegateGate(user) {
  return user.role === "super_admin" || user.role === "admin";
}

function DelegationRow({ projectId, gate, delegation, employeeName, canManage, onChanged }) {
  const [ending, setEnding] = useState(false);
  const [error, setError] = useState("");
  const isActive = delegation.status === "active";

  async function end() {
    const reason = window.prompt("Why is this delegation ending?");
    if (reason === null) return;
    if (!reason.trim()) {
      setError("A reason is required to end a delegation.");
      return;
    }
    setEnding(true);
    setError("");
    try {
      await taskExecutionApi.endGateDelegation(projectId, gate.id, delegation.id, { reason: reason.trim() });
      await onChanged();
    } catch (caught) {
      setError(caught?.message || "This delegation could not be ended.");
    } finally {
      setEnding(false);
    }
  }

  return <li className={`rounded-xl border px-3 py-2 text-sm ${isActive ? "border-slate-200 bg-white" : "border-slate-100 bg-slate-50"}`}>
    <div className="flex flex-wrap items-center gap-2">
      <UserRoundCheck size={15} className={isActive ? "text-blue-600" : "text-slate-400"}/>
      <strong className="text-slate-900">{employeeName}</strong>
      <Pill tone={isActive ? "blue" : "gray"}>{isActive ? "Chasing" : "Ended"}</Pill>
      {isActive && canManage && (
        <Button type="button" size="sm" variant="ghost" loading={ending} onClick={end}>End</Button>
      )}
    </div>
    <p className="mt-0.5 text-slate-600">{delegation.instruction}</p>
    {delegation.end_reason && <p className="mt-0.5 text-xs text-slate-500">Ended: {delegation.end_reason}</p>}
    {error && <p className="mt-1 text-xs font-bold text-rose-700">{error}</p>}
  </li>;
}

export function ExecutionGateDelegationPanel({ projectId, gate, user, internalEmployees, onChanged }) {
  const [delegations, setDelegations] = useState([]);
  const [loading, setLoading] = useState(true);
  const [showForm, setShowForm] = useState(false);
  const [employeeId, setEmployeeId] = useState("");
  const [instruction, setInstruction] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState("");

  const canManage = canDelegateGate(user);

  async function load() {
    setLoading(true);
    try {
      setDelegations(await taskExecutionApi.gateDelegations(projectId, gate.id) || []);
      setError("");
    } catch (caught) {
      setError(caught?.message || "Could not load who is chasing this approval.");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => { load(); }, [projectId, gate.id]);

  async function refreshAll() {
    await load();
    // The gate list carries active_delegate_user_ids, which decides whether
    // the delegate is offered the submit control - so it has to refetch too.
    await onChanged();
  }

  async function submit(event) {
    event.preventDefault();
    setSubmitting(true);
    setError("");
    try {
      await taskExecutionApi.delegateGate(projectId, gate.id, {
        employee_id: employeeId, instruction: instruction.trim(),
      });
      setEmployeeId("");
      setInstruction("");
      setShowForm(false);
      await refreshAll();
    } catch (caught) {
      setError(caught?.message || "This approval could not be delegated.");
    } finally {
      setSubmitting(false);
    }
  }

  const nameFor = id => internalEmployees.find(person => person.employee_id === id)?.name || "Internal Employee";
  const activeIds = new Set(delegations.filter(row => row.status === "active").map(row => row.employee_id));
  const available = internalEmployees.filter(person => !activeIds.has(person.employee_id));

  return <div className="mt-3 rounded-xl border border-slate-200 bg-slate-50/60 p-3">
    <div className="flex flex-wrap items-center justify-between gap-2">
      <strong className="text-sm text-slate-800">Chasing this approval</strong>
      {canManage && !showForm && (
        <Button type="button" size="sm" variant="secondary" onClick={() => setShowForm(true)} disabled={!available.length}>
          <UserPlus size={15}/> Delegate
        </Button>
      )}
    </div>

    {loading ? (
      <p className="mt-1.5 text-sm text-slate-500">Loading...</p>
    ) : delegations.length ? (
      <ul className="mt-2 grid list-none gap-1.5 p-0">
        {delegations.map(delegation => (
          <DelegationRow
            key={delegation.id} projectId={projectId} gate={gate} delegation={delegation}
            employeeName={nameFor(delegation.employee_id)} canManage={canManage} onChanged={refreshAll}
          />
        ))}
      </ul>
    ) : (
      <p className="mt-1.5 text-sm text-slate-500">
        Nobody is chasing this yet.{canManage ? "" : " Only an Admin can delegate it."}
      </p>
    )}

    {canManage && !available.length && !showForm && (
      <p className="mt-1.5 text-xs text-slate-500">
        Every Internal Employee on this project is already chasing it. Add one to the project team to delegate further.
      </p>
    )}

    {showForm && <form className="mt-2 grid gap-2 sm:grid-cols-2" onSubmit={submit}>
      <Field label="Internal Employee">
        <Select value={employeeId} onChange={event => setEmployeeId(event.target.value)}>
          <option value="">Select someone</option>
          {available.map(person => (
            <option key={person.employee_id} value={person.employee_id}>{person.name}</option>
          ))}
        </Select>
      </Field>
      <Field label="What are they chasing?" className="sm:col-span-2">
        <Textarea
          value={instruction} onChange={event => setInstruction(event.target.value)}
          placeholder="e.g. Chase the landlord's agent for the signed letter; escalate if nothing by Friday."
          required
        />
      </Field>
      <div className="flex gap-2 sm:col-span-2">
        <Button type="submit" size="sm" loading={submitting} disabled={!employeeId || !instruction.trim()}>Delegate</Button>
        <Button type="button" size="sm" variant="ghost" disabled={submitting} onClick={() => setShowForm(false)}>Cancel</Button>
      </div>
    </form>}

    {error && <p className="mt-2 text-sm font-bold text-rose-700">{error}</p>}
  </div>;
}
