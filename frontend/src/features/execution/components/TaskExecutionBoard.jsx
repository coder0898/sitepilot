import { ChevronDown, ChevronUp, CircleUserRound, ClipboardList, GitBranch, RefreshCw, ShieldAlert } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { taskExecutionApi } from "../../../api/taskExecutionApi";
import { Button, EmptyState, LoadingSpinner, Pill } from "../../../components/ui";
import { TaskApprovalSummary } from "./TaskApprovalSummary";
import { TaskBlockerDelayPanel } from "./TaskBlockerDelayPanel";
import { TaskDecisionModal } from "./TaskDecisionModal";
import { TaskLifecycleStepper } from "./TaskLifecycleStepper";
import { TaskProgressForm } from "./TaskProgressForm";
import { TaskSupportAssignmentPanel } from "./TaskSupportAssignmentPanel";
import { TaskTerminalSummary } from "./TaskTerminalSummary";
import { TaskVendorDelegationForm } from "./TaskVendorDelegationForm";

// U2: forward status-progression buttons, mirrored from
// TaskLifecycleService.ALLOWED_TRANSITIONS on the backend. This is a UX
// convenience only - the backend's allow-list is the actual authority, and
// a 409 from an out-of-band attempt is the real backstop (see plan
// Approach). Verify/approve/reject aren't plain buttons - those are U4's
// TaskDecisionModal, since they also write a decision record.
const FORWARD_TRANSITIONS = {
  planned: ["ready"],
  ready: ["in_progress"],
  in_progress: ["submitted"],
  rejected: ["in_progress"],
};
const CANCELLABLE_STATUSES = ["planned", "ready", "in_progress", "submitted", "verified", "approval_pending", "rejected"];
const TRANSITION_LABEL = { ready: "Mark ready", in_progress: "Start work", submitted: "Submit for review" };
const STATUS_TONE = {
  planned: "gray", ready: "blue", in_progress: "blue", submitted: "orange",
  verified: "orange", approval_pending: "orange", rejected: "red", completed: "green", cancelled: "gray",
};

const EXECUTOR_TARGETS = ["in_progress", "submitted"];

function canCancel(user) {
  return ["project_manager", "admin", "super_admin"].includes(user?.role);
}

// Mirrors task_lifecycle.py's `_require_role_for_transition`: "start"
// (in_progress) and "submit completion" (submitted) belong to the assigned
// Internal Employee once one is actively support-assigned to the task - a
// Supervisor/PM must not silently take over execution from them. Everything
// else (`ready`, reopening choices, decisions) stays Supervisor/PM/Admin.
function forwardTargetsFor(detail, user) {
  const targets = FORWARD_TRANSITIONS[detail.lifecycle_status] || [];
  if (!targets.length) return [];
  const hasAssignedEmployee = (detail.support_assignments || []).some(a => a.status === "active");
  const isAssignedActor = user?.role === "internal_employee" && detail.actor_is_assigned_support;
  const isAdmin = user?.role === "admin" || user?.role === "super_admin";
  const isSupervisorOrPm = user?.role === "supervisor" || user?.role === "project_manager";

  return targets.filter(target => {
    if (!EXECUTOR_TARGETS.includes(target)) return isSupervisorOrPm || isAdmin;
    if (hasAssignedEmployee) return isAssignedActor || isAdmin;
    return isSupervisorOrPm || isAdmin;
  });
}

// Mirrors task_lifecycle.py's own "submitted" precondition exactly: a
// progress update counts as "spent" once some TaskVerification decision
// names it as `submission_update_id`. Submission needs at least one
// progress update that isn't in that consumed set. This used to be
// approximated by comparing counts (fewer updates than decisions -> none
// left unconsumed), which breaks the moment the SAME update gets decided on
// more than once - real, observed data: a task rejected twice in a row
// before this fix existed left 2 TaskVerification rows pointing at the
// SAME 1 progress update, so "updates <= verifications" (1 <= 2) wrongly
// stayed true forever even after a genuinely new update was logged.
// Comparing the actual id set removes that whole class of mismatch.
function needsFreshProgressUpdate(detail) {
  const isWorkKind = detail.task_kind !== "milestone" && detail.task_kind !== "approval_gate";
  if (!isWorkKind) return false;
  const updates = detail.progress_updates || [];
  if (!updates.length) return true;
  const consumedIds = new Set((detail.verifications || []).map(v => v.submission_update_id));
  return updates.every(u => consumedIds.has(u.id));
}

function plannedDayLabel(task) {
  if (!task.planned_start_day) return "Pre-activation";
  if (task.planned_end_day && task.planned_end_day !== task.planned_start_day) return `Day ${task.planned_start_day}-${task.planned_end_day}`;
  return `Day ${task.planned_start_day}`;
}

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

function CancelControl({ projectId, task, onChanged }) {
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  async function cancel() {
    setBusy(true);
    setError("");
    try {
      await taskExecutionApi.transitionStatus(projectId, task.id, { target_status: "cancelled", reason });
      setReason("");
      await onChanged();
    } catch (caught) {
      setError(caught?.message || "This task could not be cancelled.");
    } finally {
      setBusy(false);
    }
  }

  return <div className="flex flex-wrap items-center gap-2">
    <input
      value={reason}
      onChange={event => setReason(event.target.value)}
      placeholder="Reason for cancellation (required)"
      className="min-h-9 min-w-[220px] flex-1 rounded-lg border border-slate-200 px-3 text-sm outline-none focus:border-rose-500"
    />
    <Button size="sm" variant="danger" disabled={!reason.trim()} loading={busy} onClick={cancel}>Cancel task</Button>
    {error && <span className="text-xs font-bold text-rose-700">{error}</span>}
  </div>;
}

function TaskDetailPanel({ projectId, task, user, onChanged }) {
  const [detail, setDetail] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [transitioning, setTransitioning] = useState("");

  async function load() {
    setLoading(true);
    setError("");
    try {
      const data = await taskExecutionApi.detail(projectId, task.id);
      setDetail(data);
    } catch (caught) {
      setError(caught?.message || "This task's detail could not be loaded.");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => { load(); }, [projectId, task.id]);

  async function refreshAll() {
    await load();
    await onChanged();
  }

  async function transition(targetStatus) {
    setTransitioning(targetStatus);
    setError("");
    try {
      await taskExecutionApi.transitionStatus(projectId, task.id, { target_status: targetStatus });
      await refreshAll();
    } catch (caught) {
      setError(caught?.message || "This transition could not be completed.");
    } finally {
      setTransitioning("");
    }
  }

  async function downloadEvidence(fileId) {
    try {
      const { blob, filename } = await taskExecutionApi.downloadEvidence(projectId, task.id, fileId);
      triggerDownload(blob, filename);
    } catch (caught) {
      setError(caught?.message || "This evidence file could not be downloaded.");
    }
  }

  if (loading) return <div className="grid min-h-32 place-items-center"><LoadingSpinner label="Loading task detail..."/></div>;
  if (!detail) return <div className="rounded-xl border border-rose-200 bg-rose-50 p-4 text-sm font-bold text-rose-700">{error || "Task detail unavailable."}</div>;

  const forwardTargets = forwardTargetsFor(detail, user);
  const showCancel = canCancel(user) && CANCELLABLE_STATUSES.includes(detail.lifecycle_status);
  // Terminal = no further outgoing transitions per task_lifecycle.py's
  // ALLOWED_TRANSITIONS (both `completed` and `cancelled` map to an empty
  // set) - none of the execution controls below apply anymore. `rejected`
  // is deliberately excluded: the backend always bounces it straight back
  // to `in_progress` in the same call, so it never persists as a state a
  // user actually sees sitting still.
  const isTerminal = detail.lifecycle_status === "completed" || detail.lifecycle_status === "cancelled";

  return <div className="grid gap-4">
    {error && <div className="rounded-xl border border-rose-200 bg-rose-50 p-3 text-sm font-bold text-rose-700">{error}</div>}

    <TaskLifecycleStepper status={detail.lifecycle_status} approvalRequired={detail.approval?.approval_required}/>
    <TaskApprovalSummary task={detail}/>

    {detail.description && <p className="text-sm leading-6 text-slate-600">{detail.description}</p>}

    {detail.predecessors.length > 0 && <section className="rounded-xl border border-slate-200 bg-slate-50 p-4">
      <h4 className="flex items-center gap-2 text-xs font-black uppercase tracking-wide text-slate-500"><GitBranch size={14}/> Predecessors</h4>
      <div className="mt-2 grid gap-2">{detail.predecessors.map(dep => <div key={dep.id} className="flex flex-wrap items-center gap-2 text-sm"><span className="font-mono text-xs font-black text-blue-700">{dep.original_code}</span><span className="text-slate-700">{dep.title}</span><Pill tone={STATUS_TONE[dep.lifecycle_status] || "gray"}>{dep.lifecycle_status}</Pill>{dep.blocking && <span className="text-[10px] font-bold text-amber-700">Blocking</span>}</div>)}</div>
    </section>}

    {isTerminal ? <TaskTerminalSummary task={detail} onDownloadEvidence={downloadEvidence}/> : <>
      {(forwardTargets.length > 0 || showCancel) && <section className="rounded-xl border border-blue-200 bg-blue-50 p-4">
        <h4 className="text-xs font-black uppercase tracking-wide text-blue-700">Status</h4>
        <div className="mt-2 flex flex-wrap items-center gap-2">
          {forwardTargets.map(target => {
            const needsProgress = target === "submitted" && needsFreshProgressUpdate(detail);
            return <Button key={target} size="sm" loading={transitioning === target} disabled={needsProgress} title={needsProgress ? "Log a new progress update below first." : undefined} onClick={() => transition(target)}>{TRANSITION_LABEL[target] || target}</Button>;
          })}
        </div>
        {forwardTargets.includes("submitted") && needsFreshProgressUpdate(detail) && <p className="mt-2 text-xs font-bold text-blue-800">Log a new progress update (a note and/or evidence) below before submitting for review.</p>}
        {showCancel && <div className="mt-3 border-t border-blue-100 pt-3"><CancelControl projectId={projectId} task={detail} onChanged={refreshAll}/></div>}
      </section>}

      <TaskDecisionModal projectId={projectId} task={detail} user={user} onDecided={refreshAll}/>

      {detail.lifecycle_status === "in_progress" && <TaskProgressForm projectId={projectId} task={detail} onSubmitted={refreshAll}/>}

      {detail.progress_updates.length > 0 && <section className="rounded-xl border border-slate-200 bg-white p-4">
        <h4 className="text-xs font-black uppercase tracking-wide text-slate-500">Progress updates</h4>
        <div className="mt-2 grid gap-2">{detail.progress_updates.map(update => <article key={update.id} className="rounded-lg border border-slate-100 bg-slate-50 p-3 text-sm">
          <div className="flex flex-wrap items-center justify-between gap-2"><span className="font-bold text-slate-800">{update.note || "Evidence submitted."}</span><time className="text-xs text-slate-400">{new Date(update.created_at).toLocaleString("en-GB")}</time></div>
          {update.evidence.length > 0 && <div className="mt-2 flex flex-wrap gap-2">{update.evidence.map(file => <button key={file.id} type="button" onClick={() => downloadEvidence(file.file_id)} className="rounded-md bg-blue-100 px-2 py-1 text-xs font-bold text-blue-700 hover:bg-blue-200">{file.original_filename}</button>)}</div>}
        </article>)}</div>
      </section>}

      {(detail.verifications.length > 0 || detail.approvals.length > 0) && <section className="rounded-xl border border-slate-200 bg-white p-4">
        <h4 className="text-xs font-black uppercase tracking-wide text-slate-500">Decisions</h4>
        <div className="mt-2 grid gap-2">
          {detail.verifications.map(v => <div key={v.id} className="flex flex-wrap items-center gap-2 text-sm"><Pill tone={v.decision === "verified" ? "green" : "red"}>{v.decision}</Pill><span className="text-slate-600">Verified · {new Date(v.verified_at).toLocaleString("en-GB")}{v.verified_by_name ? ` by ${v.verified_by_name}` : ""}</span>{v.remarks && <span className="text-slate-500">- {v.remarks}</span>}</div>)}
          {detail.approvals.map(a => <div key={a.id} className="flex flex-wrap items-center gap-2 text-sm"><Pill tone={a.decision === "approved" ? "green" : "red"}>{a.decision}</Pill><span className="text-slate-600">Approved · {new Date(a.decided_at).toLocaleString("en-GB")}{a.decided_by_name ? ` by ${a.decided_by_name}` : ""}</span>{a.remarks && <span className="text-slate-500">- {a.remarks}</span>}</div>)}
        </div>
      </section>}

      {/* U5: blockers/delays are independent of lifecycle_status, so this
          panel (log form + history + resolve) is always visible while the
          task is still in flight, not gated by task state or role - any
          active project member may log one. */}
      <TaskBlockerDelayPanel projectId={projectId} task={detail} onChanged={refreshAll}/>

      {/* U2/U3: vendor delegation, acknowledgement, and activity/incident
          capture - purely additive to the task, so shown alongside
          blockers/support rather than gated by lifecycle_status or role
          (TaskVendorDelegationForm itself only offers the delegate form to
          a PM/Admin actor; the history is visible to any project member). */}
      <TaskVendorDelegationForm projectId={projectId} task={detail} user={user} onChanged={refreshAll}/>

      <details className="group rounded-xl border border-slate-200 bg-white">
        <summary className="flex cursor-pointer list-none items-center justify-between px-4 py-3 text-xs font-black uppercase tracking-wide text-slate-500">
          <span className="flex items-center gap-2">Support assignments{detail.support_assignments.length > 0 && <Pill tone="blue">{detail.support_assignments.filter(a => a.status === "active").length} active</Pill>}</span>
          <ChevronDown size={15} className="text-slate-400 transition group-open:rotate-180"/>
        </summary>
        <div className="border-t border-slate-100 p-4 pt-3">
          <TaskSupportAssignmentPanel projectId={projectId} task={detail} onChanged={refreshAll}/>
        </div>
      </details>
    </>}
  </div>;
}

export function TaskExecutionBoard({ projectId, user, search = "" }) {
  const [tasks, setTasks] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [expandedId, setExpandedId] = useState(null);
  // Guards against an out-of-order response after a fast project switch
  // (e.g. Project A's slow list resolves after Project B's fast one) -
  // mirrors the `active` flag pattern used elsewhere in this file/diff.
  const currentProjectIdRef = useRef(projectId);
  useEffect(() => { currentProjectIdRef.current = projectId; }, [projectId]);

  async function load() {
    const requestedProjectId = projectId;
    setLoading(true);
    setError("");
    try {
      const items = await taskExecutionApi.list(requestedProjectId);
      if (currentProjectIdRef.current !== requestedProjectId) return;
      setTasks(items);
    } catch (caught) {
      if (currentProjectIdRef.current !== requestedProjectId) return;
      setError(caught?.message || "The task execution board could not be loaded.");
    } finally {
      if (currentProjectIdRef.current === requestedProjectId) setLoading(false);
    }
  }

  useEffect(() => { load(); }, [projectId]);

  const term = search.trim().toLowerCase();
  const filtered = term
    ? tasks.filter(task => [task.original_code, task.title, task.category, task.phase].some(value => value && value.toLowerCase().includes(term)))
    : tasks;

  if (loading) return <div className="rounded-2xl border border-slate-200 bg-white p-8"><LoadingSpinner label="Loading task execution board..."/></div>;
  if (error) return <div className="rounded-2xl border border-rose-200 bg-rose-50 p-5"><p className="text-sm font-bold text-rose-700">{error}</p><Button className="mt-3" variant="secondary" size="sm" onClick={load}><RefreshCw size={15}/> Retry</Button></div>;
  if (!filtered.length) return <EmptyState icon={<ClipboardList size={21}/>} title={tasks.length ? "No tasks match this search" : "No execution tasks yet"} description={tasks.length ? "Try a different search term." : user?.role === "internal_employee" ? "No task is currently assigned to you on this project." : "This project's baseline has no tasks to execute."}/>;

  return <div className="overflow-hidden rounded-2xl border border-slate-200 bg-white" aria-label="Task execution board">
    {filtered.map(task => {
      const expanded = expandedId === task.id;
      return <article key={task.id} className="border-b border-slate-100 last:border-0">
        <button type="button" className="flex w-full flex-wrap items-center gap-3 px-4 py-4 text-left sm:px-5" onClick={() => setExpandedId(expanded ? null : task.id)} aria-expanded={expanded}>
          <span className="font-mono text-xs font-black tracking-wide text-blue-700">{task.original_code}</span>
          <span className="min-w-0 flex-1"><strong className="block truncate text-sm font-black text-slate-950">{task.title}</strong><span className="mt-0.5 block text-xs text-slate-500">{[task.phase, task.category].filter(Boolean).join(" / ") || plannedDayLabel(task)}</span></span>
          {task.approval?.task_class === "class_a" && <Pill tone="yellow">Class A</Pill>}
          {task.approval?.approval_required && <Pill tone="orange">Approval required</Pill>}
          {task.open_blocker_count > 0 && <Pill tone="orange"><ShieldAlert size={12}/> {task.open_blocker_count} blocker{task.open_blocker_count === 1 ? "" : "s"}</Pill>}
          {task.active_support_count > 0 && <Pill tone="blue"><CircleUserRound size={12}/> {task.active_support_count} support</Pill>}
          <Pill tone={STATUS_TONE[task.lifecycle_status] || "gray"}>{task.lifecycle_status.replaceAll("_", " ")}</Pill>
          {expanded ? <ChevronUp size={18} className="text-slate-400"/> : <ChevronDown size={18} className="text-slate-400"/>}
        </button>
        {expanded && <div className="border-t border-slate-100 bg-slate-50/60 px-4 py-4 sm:px-5"><TaskDetailPanel projectId={projectId} task={task} user={user} onChanged={load}/></div>}
      </article>;
    })}
  </div>;
}
