import { AlertTriangle, ClipboardCheck, ShieldCheck } from "lucide-react";
import { useEffect, useState } from "react";
import { projectsApi } from "../../../api/projectsApi";
import { taskExecutionApi } from "../../../api/taskExecutionApi";
import { Button, Field, LoadingSpinner, Modal, Pill, Textarea } from "../../../components/ui";
import { formatDateShort } from "../../../utils/format";
import { actorProjectRoles } from "./TaskExecutionBoard";

// U18: the Execution tab's external approvals, now decidable.
//
// This reads the EXECUTION-layer approvals (U8 instantiates them at
// activation, U11 decides them), not the planning-layer gates this tab used
// to show. The planning gate's `status` is a Draft-time review marker written
// only while the project is still a draft; it answered a different question
// and could never move once the project went live, which is why the tab was
// read-only. Nothing could grant an approval, so every approval readiness
// waits on stayed pending forever.

const STATUS_TONE = { pending: "orange", approved: "green", rejected: "red" };

// Mirrors ProjectGateDecisionService._require_approver exactly: Admin and
// Super Admin pass unconditionally, otherwise the actor must hold an active
// project_manager membership ON THIS PROJECT. Read access is deliberately
// wider - any active member can see the list - so a Supervisor sees what is
// holding up their site without being offered an action that would 403.
function canDecide(user, roles) {
  if (user?.role === "admin" || user?.role === "super_admin") return true;
  return roles.includes("project_manager");
}

function DecisionModal({ approval, decision, onConfirm, onClose }) {
  const [reason, setReason] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState("");
  const rejecting = decision === "rejected";

  async function submit(event) {
    event.preventDefault();
    const cleanReason = reason.trim();
    if (rejecting && !cleanReason) {
      setError("A reason is required to reject this approval.");
      return;
    }
    setSubmitting(true);
    setError("");
    try {
      await onConfirm(cleanReason || null);
    } catch (caught) {
      setError(caught?.message || "This decision could not be recorded.");
      setSubmitting(false);
    }
  }

  return <Modal
    title={rejecting ? "Reject external approval" : "Approve external approval"}
    subtitle={`${approval.gate_code} - ${approval.gate_name}`}
    onClose={() => { if (!submitting) onClose(); }}
    className="sm:max-w-xl"
  >
    <form className="grid gap-4" onSubmit={submit}>
      {approval.blocking && !rejecting && <p className="rounded-xl border border-blue-200 bg-blue-50 px-4 py-3 text-sm font-bold text-blue-800">
        This approval blocks {approval.covered_task_ids.length} task{approval.covered_task_ids.length === 1 ? "" : "s"}. Approving it releases them.
      </p>}
      <Field label={rejecting ? "Reason for rejection (required)" : "Remarks (optional)"}>
        <Textarea
          value={reason}
          onChange={event => setReason(event.target.value)}
          required={rejecting}
          placeholder={rejecting ? "Explain why this approval is being refused" : "Optional remarks for the record"}
        />
      </Field>
      {error && <div role="alert" className="rounded-xl border border-rose-200 bg-rose-50 px-4 py-3 text-sm font-bold text-rose-700">{error}</div>}
      <div className="grid gap-2 sm:grid-cols-2">
        <Button type="button" variant="secondary" disabled={submitting} onClick={onClose}>Cancel</Button>
        <Button type="submit" variant={rejecting ? "danger" : "primary"} disabled={rejecting && !reason.trim()} loading={submitting}>
          {rejecting ? "Confirm rejection" : "Confirm approval"}
        </Button>
      </div>
    </form>
  </Modal>;
}

export function ExternalApprovalsPanel({ projectId, project, user }) {
  const [approvals, setApprovals] = useState([]);
  // The PLANNING-layer gates, read only to explain an empty list. An approval
  // is instantiated at activation from a gate a PM marked applicable, so a
  // project whose gates are all still awaiting that decision has none here -
  // and saying only "none were instantiated" describes our mechanism while
  // leaving the user believing the project has no external approvals at all,
  // when it may have dozens sitting undecided in setup.
  const [awaitingReview, setAwaitingReview] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [pendingDecision, setPendingDecision] = useState(null); // { approval, decision }

  async function load() {
    setLoading(true);
    setError("");
    try {
      setApprovals(await taskExecutionApi.listExternalApprovals(projectId));
    } catch (caught) {
      setError(caught?.message || "This project's external approvals could not be loaded.");
    } finally {
      setLoading(false);
    }
    // Deliberately after, and deliberately swallowed: this read only enriches
    // an explanation. Failing it must never blank the approvals a user can
    // actually act on.
    try {
      const gates = await projectsApi.externalGates(projectId);
      const items = gates?.items || gates || [];
      setAwaitingReview(items.filter(gate => (gate.applicability_state || "pending_review") === "pending_review").length);
    } catch {
      setAwaitingReview(0);
    }
  }

  useEffect(() => { load(); }, [projectId]);

  const roles = actorProjectRoles(project, user);
  const mayDecide = canDecide(user, roles);

  // Reloads this list so the decided approval shows its new status. The task
  // board's readiness is refreshed by its own remount when the user returns
  // to the Tasks tab - see the note in ExecutionPage.jsx.
  async function decide(approval, decision, reason) {
    await taskExecutionApi.decideExternalApproval(projectId, approval.id, { decision, reason });
    setPendingDecision(null);
    await load();
  }

  if (loading) return <div className="rounded-2xl border border-slate-200 bg-white p-8"><LoadingSpinner label="Loading external approvals..."/></div>;

  return <div className="rounded-2xl border border-slate-200 bg-white p-5">
    <h3 className="m-0 font-serif text-lg text-slate-950">External approvals</h3>
    <p className="mt-1 text-sm text-slate-500">
      {mayDecide
        ? "Approve or reject the external approvals this project's tasks are waiting on."
        : "The external approvals this project's tasks are waiting on. Only the project's PM or an Admin can decide them."}
    </p>

    {error && <div className="mt-3 rounded-xl border border-rose-200 bg-rose-50 px-4 py-3 text-sm font-bold text-rose-700">{error}</div>}

    {/* Shown whenever gates are still undecided, not only when the list is
        empty: a project can have three approvals here and twenty more nobody
        has ruled on, and the three would otherwise read as the whole set. */}
    {awaitingReview > 0 && <div className="mt-3 flex items-start gap-2 rounded-xl border border-amber-200 bg-amber-50 px-4 py-3">
      <ClipboardCheck size={16} className="mt-0.5 shrink-0 text-amber-700"/>
      <p className="text-sm font-bold leading-6 text-amber-900">
        {awaitingReview} external approval{awaitingReview === 1 ? " is" : "s are"} awaiting applicability review.
        <span className="block font-medium">
          {awaitingReview === 1 ? "It becomes" : "They become"} approvable here once someone decides, in this project's setup, whether {awaitingReview === 1 ? "it applies" : "they apply"} to this project. Until then {awaitingReview === 1 ? "it holds" : "they hold"} nothing up.
        </span>
      </p>
    </div>}

    {!approvals.length && !error && awaitingReview === 0 ? <p className="mt-3 text-sm text-slate-500">No external approvals apply to this project.</p> : !approvals.length ? null : <div className="mt-4 grid gap-3">
      {approvals.map(approval => <article key={approval.id} className="rounded-2xl border border-slate-200 bg-white p-4">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div className="min-w-0">
            <div className="flex flex-wrap items-center gap-2">
              <span className="text-xs font-black text-blue-700">{approval.gate_code}</span>
              <Pill tone={STATUS_TONE[approval.status] || "gray"}>{approval.status}</Pill>
              {approval.blocking ? <Pill tone="orange">Blocking</Pill> : <Pill tone="gray">Non-blocking</Pill>}
              {/* R10: an approval whose coverage could not be resolved links
                  no tasks at all, so it can never appear as a task's
                  readiness reason. Saying so here is the only place a PM
                  finds out the scope still needs closing by hand. */}
              {approval.coverage_state === "unresolved" && <Pill tone="red"><AlertTriangle size={12}/> Coverage unresolved</Pill>}
            </div>
            <h4 className="mt-2 font-black text-slate-950">{approval.gate_name}</h4>
            {approval.coverage_state === "unresolved" && <p className="mt-1 max-w-prose text-sm text-slate-600">
              Scope was described in prose and could not be mapped to tasks automatically{approval.coverage_text ? `: "${approval.coverage_text}"` : "."}
            </p>}
          </div>
          <div className="text-right text-xs font-bold text-slate-500">
            <span className="flex items-center gap-1"><ShieldCheck size={13}/> {approval.covered_task_ids.length} task{approval.covered_task_ids.length === 1 ? "" : "s"} covered</span>
            {approval.decided_at && <span className="mt-1 block text-slate-400">
              {approval.status} {formatDateShort(approval.decided_at.slice(0, 10))}{approval.decided_by_name ? ` by ${approval.decided_by_name}` : ""}
            </span>}
          </div>
        </div>

        {approval.status === "pending" && mayDecide && <div className="mt-4 flex flex-wrap gap-2 border-t border-slate-100 pt-3">
          <Button size="sm" onClick={() => setPendingDecision({ approval, decision: "approved" })}>Approve</Button>
          <Button size="sm" variant="danger" onClick={() => setPendingDecision({ approval, decision: "rejected" })}>Reject</Button>
        </div>}
      </article>)}
    </div>}

    {pendingDecision && <DecisionModal
      approval={pendingDecision.approval}
      decision={pendingDecision.decision}
      onConfirm={reason => decide(pendingDecision.approval, pendingDecision.decision, reason)}
      onClose={() => setPendingDecision(null)}
    />}
  </div>;
}
