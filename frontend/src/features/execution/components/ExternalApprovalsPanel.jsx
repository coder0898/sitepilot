import { AlertTriangle, ClipboardCheck, Paperclip, ShieldCheck } from "lucide-react";
import { useEffect, useState } from "react";
import { projectsApi } from "../../../api/projectsApi";
import { taskExecutionApi } from "../../../api/taskExecutionApi";
import { Button, Field, LoadingSpinner, Modal, Pill, Select, Textarea } from "../../../components/ui";
import { formatDateShort } from "../../../utils/format";

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

// Plan: External Approval Gate Assignment & Evidence Lifecycle (U6).
//
// Reads the EXECUTION-layer approvals (U8 instantiates them at activation,
// U11/U5 decides them), not the planning-layer gates this tab used to show.
// The lifecycle is now unassigned -> assigned -> submitted -> approved |
// rejected, with rejection looping back to assigned for the same assignee to
// resubmit (R4). Admin exclusively assigns/reassigns/unassigns and decides
// (R1/R3/R6, no PM-fallback tier); the assignee exclusively submits evidence
// (R2); PM/Supervisor keep read-only visibility throughout.

const STATUS_TONE = {
  unassigned: "gray", assigned: "blue", submitted: "orange", approved: "green", rejected: "red",
};
const STATUS_LABEL = {
  unassigned: "Unassigned", assigned: "Assigned", submitted: "Submitted for review",
  approved: "Approved", rejected: "Rejected",
};
// Gates needing action sort ahead of settled ones, for both the actionable
// (Admin/assignee) and read-only (PM/Supervisor) views alike, so everyone
// looks at the same "what needs attention" ordering.
const STATUS_SORT_RANK = { submitted: 0, unassigned: 1, assigned: 2, rejected: 2, approved: 3 };

function isPlatformAdmin(user) {
  return user?.role === "admin" || user?.role === "super_admin";
}

// Mirrors ProjectGateDecisionService._require_approver / _require_assigner
// exactly: Admin-only, no PM-fallback tier for this flow (R1/R3/R6) - a
// deliberate divergence from the task verify/approve pattern.
function canManage(user) {
  return isPlatformAdmin(user);
}

function isAssignee(approval, user) {
  return !!user && approval.assigned_to_user_id === user.id;
}

function AssignModal({ approval, candidates, title, confirmLabel, onConfirm, onClose }) {
  const [employeeId, setEmployeeId] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState("");

  async function submit(event) {
    event.preventDefault();
    setSubmitting(true);
    setError("");
    try {
      await onConfirm(employeeId);
    } catch (caught) {
      // A 409 here specifically means someone else assigned/decided this
      // gate in the interim (single-writer) - surfaced the same as any
      // other refusal, with the message the backend already gives.
      setError(caught?.message || "This assignment could not be recorded.");
      setSubmitting(false);
    }
  }

  return <Modal title={title} subtitle={`${approval.gate_code} - ${approval.gate_name}`} onClose={() => { if (!submitting) onClose(); }} className="sm:max-w-xl">
    <form className="grid gap-4" onSubmit={submit}>
      <Field label="Internal Employee">
        <Select value={employeeId} onChange={event => setEmployeeId(event.target.value)} required>
          <option value="">{candidates.length ? "Select employee" : "No eligible employees on this project"}</option>
          {candidates.map(candidate => <option key={candidate.user_id} value={candidate.user_id}>{candidate.name}</option>)}
        </Select>
      </Field>
      {error && <div role="alert" className="rounded-xl border border-rose-200 bg-rose-50 px-4 py-3 text-sm font-bold text-rose-700">{error}</div>}
      <div className="grid gap-2 sm:grid-cols-2">
        <Button type="button" variant="secondary" disabled={submitting} onClick={onClose}>Cancel</Button>
        <Button type="submit" disabled={!employeeId} loading={submitting}>{confirmLabel}</Button>
      </div>
    </form>
  </Modal>;
}

function SubmissionForm({ projectId, approval, onSubmitted }) {
  const [note, setNote] = useState("");
  const [files, setFiles] = useState([]);
  const [fileError, setFileError] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState("");

  function pickFiles(event) {
    const chosen = Array.from(event.target.files || []);
    setFiles(chosen);
    // Mirrors the backend allowlist (task_progress.py/project_gate_submission.py)
    // so a disallowed type is caught before the round trip, not just after.
    const disallowed = chosen.find(file => !["image/jpeg", "image/png", "image/webp", "application/pdf"].includes(file.type));
    setFileError(disallowed ? `${disallowed.name} must be JPG, PNG, WebP, or PDF.` : "");
  }

  async function submit(event) {
    event.preventDefault();
    setSubmitting(true);
    setError("");
    try {
      const formData = new FormData();
      if (note.trim()) formData.append("note", note.trim());
      files.forEach(file => formData.append("evidence", file));
      await taskExecutionApi.submitExternalApprovalEvidence(projectId, approval.id, formData);
      setNote("");
      setFiles([]);
      await onSubmitted();
    } catch (caught) {
      setError(caught?.message || "This submission could not be recorded.");
    } finally {
      setSubmitting(false);
    }
  }

  return <section className="mt-4 rounded-xl border border-emerald-200 bg-emerald-50 p-4">
    {approval.rejection_reason && <p className="mb-3 rounded-xl border border-rose-200 bg-rose-50 px-4 py-3 text-sm font-bold text-rose-800">
      Sent back for resubmission: {approval.rejection_reason}
    </p>}
    <h4 className="text-xs font-black uppercase tracking-wide text-emerald-800">Submit evidence</h4>
    <form className="mt-3 grid gap-3" onSubmit={submit}>
      <Field label="Note"><Textarea className="min-h-20" value={note} onChange={event => setNote(event.target.value)} placeholder="Describe what's attached, or any context for the reviewer"/></Field>
      <label className="grid gap-2 text-sm font-bold text-slate-700">Documents or photos (optional)
        <input className="w-full cursor-pointer rounded-xl border border-slate-200 bg-white text-sm font-normal text-slate-600 file:mr-4 file:border-0 file:bg-emerald-700 file:px-3 file:py-2 file:font-bold file:text-white hover:file:bg-emerald-800" type="file" multiple accept="image/jpeg,image/png,image/webp,application/pdf" onChange={pickFiles}/>
      </label>
      {fileError && <p className="text-xs font-bold text-rose-700">{fileError}</p>}
      {error && <div role="alert" className="rounded-xl border border-rose-200 bg-rose-50 px-3 py-2 text-sm font-bold text-rose-700">{error}</div>}
      <Button type="submit" size="sm" loading={submitting} disabled={!!fileError || (!note.trim() && !files.length)}>Submit for review</Button>
    </form>
  </section>;
}

// Review context for Admin deciding a `submitted` gate, and history for
// everyone else (R6) - without this, there was no way to see what the
// assignee actually attached, the same gap TaskExecutionBoard's evidence
// list closes for task review.
function SubmissionHistory({ projectId, approval }) {
  const [error, setError] = useState("");
  const submissions = approval.submissions || [];
  if (!submissions.length) return null;

  async function download(fileId, filename) {
    setError("");
    try {
      const { blob } = await taskExecutionApi.downloadExternalApprovalEvidence(projectId, approval.id, fileId);
      triggerDownload(blob, filename);
    } catch (caught) {
      setError(caught?.message || "This evidence file could not be downloaded.");
    }
  }

  return <section className="mt-4 border-t border-slate-100 pt-3">
    <h5 className="text-xs font-black uppercase tracking-wide text-slate-500">Submission history</h5>
    <div className="mt-2 grid gap-2">
      {submissions.map(submission => <article key={submission.id} className="rounded-lg border border-slate-100 bg-slate-50 p-3 text-sm">
        <div className="flex flex-wrap items-center justify-between gap-2 text-xs font-bold text-slate-500">
          <span>{submission.submitted_by_name || "Unknown"}</span>
          <span>{formatDateShort(submission.submitted_at.slice(0, 10))}</span>
        </div>
        {submission.note && <p className="mt-1 text-slate-700">{submission.note}</p>}
        {submission.evidence.length > 0 && <div className="mt-2 flex flex-wrap gap-2">
          {submission.evidence.map(file => <button key={file.id} type="button" onClick={() => download(file.file_id, file.original_filename)} className="flex items-center gap-1 rounded-md bg-blue-100 px-2 py-1 text-xs font-bold text-blue-700 hover:bg-blue-200">
            <Paperclip size={12}/>{file.original_filename}
          </button>)}
        </div>}
      </article>)}
    </div>
    {error && <p className="mt-2 text-xs font-bold text-rose-700">{error}</p>}
  </section>;
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
      {rejecting && <p className="rounded-xl border border-amber-200 bg-amber-50 px-4 py-3 text-sm font-bold text-amber-900">
        Rejecting sends this back to {approval.assigned_to_name || "the assignee"} to fix and resubmit.
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

function sortApprovals(approvals) {
  return [...approvals].sort((a, b) => {
    const rank = (STATUS_SORT_RANK[a.status] ?? 9) - (STATUS_SORT_RANK[b.status] ?? 9);
    return rank !== 0 ? rank : a.gate_code.localeCompare(b.gate_code);
  });
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
  const [assigning, setAssigning] = useState(null); // { approval, mode: "assign" | "reassign" }
  const [unassignError, setUnassignError] = useState("");

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

  const mayManage = canManage(user);
  const candidates = (project?.memberships || [])
    .filter(membership => membership.project_role === "internal_employee" && !membership.ends_at);

  async function decide(approval, decision, reason) {
    await taskExecutionApi.decideExternalApproval(projectId, approval.id, { decision, reason });
    setPendingDecision(null);
    await load();
  }

  async function assign(approval, mode, assigneeUserId) {
    const call = mode === "reassign" ? taskExecutionApi.reassignExternalApproval : taskExecutionApi.assignExternalApproval;
    await call(projectId, approval.id, { assignee_user_id: assigneeUserId });
    setAssigning(null);
    await load();
  }

  async function unassign(approval) {
    setUnassignError("");
    try {
      await taskExecutionApi.unassignExternalApproval(projectId, approval.id);
      await load();
    } catch (caught) {
      setUnassignError(caught?.message || "This gate could not be unassigned.");
    }
  }

  if (loading) return <div className="rounded-2xl border border-slate-200 bg-white p-8"><LoadingSpinner label="Loading external approvals..."/></div>;

  const sorted = sortApprovals(approvals);

  return <div className="rounded-2xl border border-slate-200 bg-white p-5">
    <h3 className="m-0 font-serif text-lg text-slate-950">External approvals</h3>
    <p className="mt-1 text-sm text-slate-500">
      {mayManage
        ? "Assign these external approvals to an Internal Employee, then approve or reject what they submit."
        : "The external approvals this project's tasks are waiting on. Only an Admin can assign or decide them."}
    </p>

    {error && <div className="mt-3 rounded-xl border border-rose-200 bg-rose-50 px-4 py-3 text-sm font-bold text-rose-700">{error}</div>}
    {unassignError && <div className="mt-3 rounded-xl border border-rose-200 bg-rose-50 px-4 py-3 text-sm font-bold text-rose-700">{unassignError}</div>}

    {/* Shown whenever gates are still undecided, not only when the list is
        empty: a project can have three approvals here and twenty more nobody
        has ruled on, and the three would otherwise read as the whole set. */}
    {awaitingReview > 0 && <div className="mt-3 flex items-start gap-2 rounded-xl border border-amber-200 bg-amber-50 px-4 py-3">
      <ClipboardCheck size={16} className="mt-0.5 shrink-0 text-amber-700"/>
      <p className="text-sm font-bold leading-6 text-amber-900">
        {awaitingReview} external approval{awaitingReview === 1 ? " is" : "s are"} awaiting applicability review.
        <span className="block font-medium">
          {awaitingReview === 1 ? "It becomes" : "They become"} assignable here once someone decides, in this project's setup, whether {awaitingReview === 1 ? "it applies" : "they apply"} to this project. Until then {awaitingReview === 1 ? "it holds" : "they hold"} nothing up.
        </span>
      </p>
    </div>}

    {!sorted.length && !error && awaitingReview === 0 ? <p className="mt-3 text-sm text-slate-500">No external approvals apply to this project.</p> : !sorted.length ? null : <div className="mt-4 grid gap-3">
      {sorted.map(approval => {
        const assignedToMe = isAssignee(approval, user);
        return <article key={approval.id} className="rounded-2xl border border-slate-200 bg-white p-4">
          <div className="flex flex-wrap items-start justify-between gap-3">
            <div className="min-w-0">
              <div className="flex flex-wrap items-center gap-2">
                <span className="text-xs font-black text-blue-700">{approval.gate_code}</span>
                <Pill tone={STATUS_TONE[approval.status] || "gray"}>{STATUS_LABEL[approval.status] || approval.status}</Pill>
                {approval.blocking ? <Pill tone="orange">Blocking</Pill> : <Pill tone="gray">Non-blocking</Pill>}
                {approval.status === "assigned" && approval.rejection_reason && <Pill tone="red"><AlertTriangle size={12}/> Sent back for resubmission</Pill>}
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
              {approval.assigned_to_name && <span className="mt-1 block text-slate-400">Assigned to {approval.assigned_to_name}</span>}
              {approval.decided_at && <span className="mt-1 block text-slate-400">
                {approval.status} {formatDateShort(approval.decided_at.slice(0, 10))}{approval.decided_by_name ? ` by ${approval.decided_by_name}` : ""}
              </span>}
            </div>
          </div>

          {mayManage && approval.status === "unassigned" && <div className="mt-4 flex flex-wrap gap-2 border-t border-slate-100 pt-3">
            <Button size="sm" onClick={() => setAssigning({ approval, mode: "assign" })}>Assign</Button>
          </div>}

          {mayManage && (approval.status === "assigned" || approval.status === "submitted") && <div className="mt-4 flex flex-wrap gap-2 border-t border-slate-100 pt-3">
            <Button size="sm" variant="secondary" onClick={() => setAssigning({ approval, mode: "reassign" })}>Reassign</Button>
            <Button size="sm" variant="secondary" onClick={() => unassign(approval)}>Unassign</Button>
          </div>}

          {mayManage && approval.status === "submitted" && <div className="mt-2 flex flex-wrap gap-2">
            <Button size="sm" onClick={() => setPendingDecision({ approval, decision: "approved" })}>Approve</Button>
            <Button size="sm" variant="danger" onClick={() => setPendingDecision({ approval, decision: "rejected" })}>Reject</Button>
          </div>}

          <SubmissionHistory projectId={projectId} approval={approval}/>

          {assignedToMe && approval.status === "assigned" && <SubmissionForm projectId={projectId} approval={approval} onSubmitted={load}/>}
        </article>;
      })}
    </div>}

    {assigning && <AssignModal
      approval={assigning.approval}
      candidates={candidates}
      title={assigning.mode === "reassign" ? "Reassign external approval" : "Assign external approval"}
      confirmLabel={assigning.mode === "reassign" ? "Reassign" : "Assign"}
      onConfirm={assigneeUserId => assign(assigning.approval, assigning.mode, assigneeUserId)}
      onClose={() => setAssigning(null)}
    />}

    {pendingDecision && <DecisionModal
      approval={pendingDecision.approval}
      decision={pendingDecision.decision}
      onConfirm={reason => decide(pendingDecision.approval, pendingDecision.decision, reason)}
      onClose={() => setPendingDecision(null)}
    />}
  </div>;
}
