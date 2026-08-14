import { CalendarClock, ChevronDown, ChevronUp, CircleUserRound, ClipboardList, GitBranch, Paperclip, RefreshCw, ShieldAlert } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { projectsApi } from "../../../api/projectsApi";
import { taskExecutionApi } from "../../../api/taskExecutionApi";
import { Button, EmptyState, Field, LoadingSpinner, Modal, Pill, Textarea } from "../../../components/ui";
import { formatDateShort, todayIso } from "../../../utils/format";
import { TaskApprovalSummary } from "./TaskApprovalSummary";
import { TaskBlockerDelayPanel } from "./TaskBlockerDelayPanel";
import { TaskDecisionModal } from "./TaskDecisionModal";
import { TaskLifecycleStepper } from "./TaskLifecycleStepper";
import { TaskProgressForm } from "./TaskProgressForm";
import { COMPUTED_READINESS_STATES, matchesReadinessFilter, readinessLabel, readinessTone, TaskReadinessPanel } from "./TaskReadinessPanel";
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

// U6: every authority check below is keyed on the actor's membership of THIS
// project, not on their global role. The backend has always worked that way -
// `_can_cancel`, `_require_role_for_transition` and
// `TaskSupportAssignmentService._require_controller` all resolve the actor's
// V2ProjectMembership rows first - but the board used to check `user.role`,
// so a PM viewing a project they are not a member of was shown Cancel and the
// forward-transition buttons and then got a 403 on click.
//
// Admin and Super Admin are the one genuine global authority: they short-
// circuit every backend check, so they short-circuit these too.
function isPlatformAdmin(user) {
  return user?.role === "admin" || user?.role === "super_admin";
}

// Roles the actor holds on this specific project, derived from the project's
// active memberships. Empty for a non-member, which is exactly the case the
// old global-role check got wrong.
export function actorProjectRoles(project, user) {
  if (!project || !user) return [];
  return (project.memberships || [])
    .filter(membership => membership.user_id === user.id && !membership.ends_at)
    .map(membership => membership.project_role);
}

// Mirrors task_lifecycle.py's `_can_cancel`: Admin/Super Admin, or the
// project's own PM.
function canCancel(user, roles) {
  return isPlatformAdmin(user) || roles.includes("project_manager");
}

// Mirrors TaskSupportAssignmentService._require_controller: the Supervisor
// controls support for work tasks, the PM for approval gates, and a milestone
// has no support concept at all.
function canAssignSupport(detail, user, roles) {
  if (isPlatformAdmin(user)) return true;
  if (detail.task_kind === "approval_gate") return roles.includes("project_manager");
  if (detail.task_kind === "milestone") return false;
  return roles.includes("site_supervisor");
}

// Mirrors task_lifecycle.py's `_require_role_for_transition`: "start"
// (in_progress) and "submit completion" (submitted) belong to the assigned
// Internal Employee once one is actively support-assigned to the task - a
// Supervisor/PM must not silently take over execution from them. Everything
// else (`ready`, reopening choices, decisions) stays Supervisor/PM/Admin.
// Shared with the "Log progress" form below: whoever may drive
// start/submit is exactly who may log the progress evidence those
// transitions consume, per task_lifecycle.py/task_progress.py's identical
// executor-driven check.
function canExecute(detail, user, roles) {
  const hasAssignedEmployee = (detail.support_assignments || []).some(a => a.status === "active");
  const isAssignedActor = user?.role === "internal_employee" && detail.actor_is_assigned_support;
  if (isPlatformAdmin(user)) return true;
  if (hasAssignedEmployee) return isAssignedActor;
  // Approval-gate work has no Supervisor/PM self-execute fallback: the
  // backend refuses to let anyone start it until an Internal Employee is
  // delegated. Offering the button here would always 409.
  if (detail.task_kind === "approval_gate") return false;
  return roles.includes("site_supervisor") || roles.includes("project_manager");
}

function forwardTargetsFor(detail, user, roles) {
  const targets = FORWARD_TRANSITIONS[detail.lifecycle_status] || [];
  if (!targets.length) return [];
  // Scheduling (`ready`) is Supervisor/PM authority on this project;
  // start/submit follow the executor rule in canExecute.
  const canSchedule = isPlatformAdmin(user)
    || roles.includes("site_supervisor")
    || roles.includes("project_manager");
  const canExec = canExecute(detail, user, roles);

  return targets.filter(target => (
    EXECUTOR_TARGETS.includes(target) ? canExec : canSchedule
  ));
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
// Returns null when the task can be submitted for review, otherwise which
// precondition is unmet - so the board can name what is missing instead of
// showing a bare disabled button.
//
// "progress": the backend's own rule, mirrored exactly. A progress update
// counts as spent once some TaskVerification decision names it as
// `submission_update_id`; submission needs at least one that is not.
// Comparing the id set rather than counts matters because the SAME update can
// be decided on more than once - a task rejected twice leaves two decisions
// pointing at one update, and a count comparison stays wrongly true forever.
//
// "evidence": U22. A task authored as evidence-required needs a file on the
// update it is submitting, not merely a note. `evidence_required` has been
// carried on the task payload since the API existed and was rendered nowhere,
// so the flag was invisible and the rule unenforced on this surface.
function submitBlocker(detail) {
  const isWorkKind = detail.task_kind !== "milestone" && detail.task_kind !== "approval_gate";
  if (!isWorkKind) return null;
  const consumedIds = new Set((detail.verifications || []).map(v => v.submission_update_id));
  const unreviewed = (detail.progress_updates || []).filter(update => !consumedIds.has(update.id));
  if (!unreviewed.length) return "progress";
  if (detail.evidence_required && !unreviewed.some(update => (update.evidence || []).length > 0)) return "evidence";
  return null;
}

const SUBMIT_BLOCKER_MESSAGE = {
  progress: "Log a new progress update (a note and/or evidence) below before submitting for review.",
  evidence: "This task requires evidence. Attach a photo or PDF to a new progress update below before submitting for review.",
};

function plannedDayLabel(task) {
  if (!task.planned_start_day) return "Pre-activation";
  if (task.planned_end_day && task.planned_end_day !== task.planned_start_day) return `Day ${task.planned_start_day}-${task.planned_end_day}`;
  return `Day ${task.planned_start_day}`;
}

// U23: whether starting this task now would be starting it ahead of plan.
// Mirrors task_lifecycle.py's own early-start condition exactly - target
// `in_progress`, no actual start recorded yet, a planned start date exists,
// and today is before it - because the backend REFUSES the transition
// without a reason. Getting this wrong in either direction is visible: too
// eager and we demand a reason the backend does not want, too lax and the
// user is refused with no way to answer.
//
// `todayIso()` is UTC, matching the clock the backend compares against and
// stamps `actual_start_at` from. A local-midnight "today" would disagree
// with the server for several hours a day either side of the boundary.
//
// The date comes from `planned_start_date` on the payload, never re-derived
// from the day offsets: U9 owns that conversion on the backend, and a second
// copy of the rule here would drift from it.
function isEarlyStart(task) {
  if (!task?.planned_start_date) return false;
  // Only the FIRST start can be early. A rejected task reopening through
  // `in_progress` is resuming work that already began, not starting ahead of
  // plan - the backend applies the same `actual_start_at is None` guard, so
  // re-prompting here would ask for a reason it would then ignore.
  if (task.actual_start_at) return false;
  return todayIso() < task.planned_start_date;
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

// U23: collects the reason the backend requires before an early start,
// rather than letting the user click Start and be refused with a 422 they
// cannot answer. Follows TaskDecisionModal's shape - required free text,
// submit gated on it being non-empty, in-flight disabled state, and the
// server's own message inline on failure.
//
// `onConfirm` deliberately does NOT swallow its error: a failed early start
// must leave the task untouched and show why here, inside the modal the user
// is still looking at, instead of closing and surfacing it on the panel
// behind.
function EarlyStartModal({ task, onConfirm, onClose }) {
  const [reason, setReason] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState("");

  async function submit(event) {
    event.preventDefault();
    const cleanReason = reason.trim();
    if (!cleanReason) {
      setError("A reason is required to start this task before its planned start date.");
      return;
    }
    setSubmitting(true);
    setError("");
    try {
      await onConfirm(cleanReason);
    } catch (caught) {
      setError(caught?.message || "This task could not be started early.");
      // Only on failure: a success unmounts this modal, and the task is
      // already gone from under us by the time the refresh resolves.
      setSubmitting(false);
    }
  }

  return <Modal
    title="Start this task early"
    subtitle={`${task.original_code} - ${task.title}`}
    onClose={() => { if (!submitting) onClose(); }}
    className="sm:max-w-xl"
  >
    <form className="grid gap-4" onSubmit={submit}>
      <p className="rounded-xl border border-amber-200 bg-amber-50 px-4 py-3 text-sm font-bold text-amber-800">
        This task is planned to start on {formatDateShort(task.planned_start_date)}. Starting it now is ahead of the baseline, so it needs a reason for the record.
      </p>
      <Field label="Reason for starting early (required)">
        <Textarea
          value={reason}
          onChange={event => setReason(event.target.value)}
          required
          placeholder="Explain why this task is starting ahead of its planned date"
        />
      </Field>
      {error && <div role="alert" className="rounded-xl border border-rose-200 bg-rose-50 px-4 py-3 text-sm font-bold text-rose-700">{error}</div>}
      <div className="grid gap-2 sm:grid-cols-2">
        <Button type="button" variant="secondary" disabled={submitting} onClick={onClose}>Cancel</Button>
        <Button type="submit" disabled={!reason.trim()} loading={submitting}>Confirm early start</Button>
      </div>
    </form>
  </Modal>;
}

function TaskDetailPanel({ projectId, task, user, roles, candidates, onChanged }) {
  const [detail, setDetail] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [transitioning, setTransitioning] = useState("");
  // U23: open only while the early-start reason is being collected.
  const [earlyStartOpen, setEarlyStartOpen] = useState(false);

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

  // U23: the same transition as any other, carrying the reason the backend
  // demands. Errors are deliberately NOT caught here - EarlyStartModal shows
  // them inline and stays open, so a refused start leaves the task exactly as
  // it was with the reason still in the box.
  async function startEarly(reason) {
    setTransitioning("in_progress");
    setError("");
    try {
      await taskExecutionApi.transitionStatus(projectId, task.id, { target_status: "in_progress", reason });
      setEarlyStartOpen(false);
      await refreshAll();
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

  const forwardTargets = forwardTargetsFor(detail, user, roles);
  const showCancel = canCancel(user, roles) && CANCELLABLE_STATUSES.includes(detail.lifecycle_status);
  const blocker = submitBlocker(detail);
  // U23: computed from the detail payload, which carries the planned dates
  // and the actuals since U14/U15 put them there.
  const earlyStart = isEarlyStart(detail);
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
    {/* U18: deliberately above the controls and never wired into them.
        Readiness is advisory this release, so it explains rather than
        gates - the lifecycle buttons below still offer whatever the backend
        permits, even when readiness says blocked. */}
    <TaskReadinessPanel task={detail}/>
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
            const blocked = target === "submitted" && blocker !== null;
            // U23: an early start is relabelled and routed through the
            // reason modal instead of transitioning straight away.
            const isEarly = target === "in_progress" && earlyStart;
            return <Button
              key={target}
              size="sm"
              loading={transitioning === target}
              disabled={blocked}
              title={blocked ? SUBMIT_BLOCKER_MESSAGE[blocker] : undefined}
              onClick={() => (isEarly ? setEarlyStartOpen(true) : transition(target))}
            >{isEarly ? "Start work early" : (TRANSITION_LABEL[target] || target)}</Button>;
          })}
        </div>
        {forwardTargets.includes("in_progress") && earlyStart && <p className="mt-2 flex items-center gap-1.5 text-xs font-bold text-amber-700">
          <CalendarClock size={13}/> Planned to start {formatDateShort(detail.planned_start_date)} - starting now needs a reason.
        </p>}
        {forwardTargets.includes("submitted") && blocker && <p className="mt-2 text-xs font-bold text-blue-800">{SUBMIT_BLOCKER_MESSAGE[blocker]}</p>}
        {showCancel && <div className="mt-3 border-t border-blue-100 pt-3"><CancelControl projectId={projectId} task={detail} onChanged={refreshAll}/></div>}
      </section>}

      {earlyStartOpen && <EarlyStartModal task={detail} onConfirm={startEarly} onClose={() => setEarlyStartOpen(false)}/>}

      <TaskDecisionModal projectId={projectId} task={detail} user={user} onDecided={refreshAll}/>

      {detail.lifecycle_status === "in_progress" && canExecute(detail, user, roles) && <TaskProgressForm projectId={projectId} task={detail} onSubmitted={refreshAll}/>}

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
          <TaskSupportAssignmentPanel projectId={projectId} task={detail} candidates={candidates} canAssign={canAssignSupport(detail, user, roles)} onChanged={refreshAll}/>
        </div>
      </details>
    </>}
  </div>;
}

// `onTasksLoaded` (U19): hands the page the very array this board just drew
// its rows from, so the count tiles above it are computed from the same data
// rather than from the planning read model. That mismatch is R26: the tiles
// counted planning rows (which include tasks excluded from the plan and never
// instantiated into the execution layer) while the board listed execution
// rows, so the number above the board could never be trusted to describe it.
export function TaskExecutionBoard({ projectId, user, search = "", readinessFilter = "all", onTasksLoaded }) {
  const [tasks, setTasks] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [expandedId, setExpandedId] = useState(null);
  // The project's active memberships, fetched once for the whole board. Two
  // things read them: the actor's own roles on this project, which drive
  // every authority check, and the internal-employee candidate list the
  // support-assignment panel offers. The panel used to fetch this itself,
  // once per expanded task, for the candidate list alone.
  const [project, setProject] = useState(null);
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
      onTasksLoaded?.(items);
    } catch (caught) {
      if (currentProjectIdRef.current !== requestedProjectId) return;
      setError(caught?.message || "The task execution board could not be loaded.");
    } finally {
      if (currentProjectIdRef.current === requestedProjectId) setLoading(false);
    }
  }

  useEffect(() => { load(); }, [projectId]);

  useEffect(() => {
    let active = true;
    setProject(null);
    projectsApi.detail(projectId)
      .then(detail => { if (active) setProject(detail); })
      // A failure here must not break the board. It costs the actor their
      // membership-derived controls, which fails closed to "no authority" -
      // the safe direction, since the backend refuses anything they should
      // not have been offered anyway.
      .catch(() => { if (active) setProject(null); });
    return () => { active = false; };
  }, [projectId]);

  const roles = actorProjectRoles(project, user);
  const candidates = (project?.memberships || []).filter(m => m.project_role === "internal_employee");

  // U19: the readiness filter narrows the same list the search already
  // narrowed, using the shared predicate the page's count tiles use - so
  // "Blocked: 3" above and three rows below are the same three tasks.
  const term = search.trim().toLowerCase();
  const filtered = tasks.filter(task => {
    if (!matchesReadinessFilter(task, readinessFilter)) return false;
    if (!term) return true;
    return [task.original_code, task.title, task.category, task.phase].some(value => value && value.toLowerCase().includes(term));
  });

  if (loading) return <div className="rounded-2xl border border-slate-200 bg-white p-8"><LoadingSpinner label="Loading task execution board..."/></div>;
  if (error) return <div className="rounded-2xl border border-rose-200 bg-rose-50 p-5"><p className="text-sm font-bold text-rose-700">{error}</p><Button className="mt-3" variant="secondary" size="sm" onClick={load}><RefreshCw size={15}/> Retry</Button></div>;
  // Three different empty states, because they mean three different things:
  // nothing to execute at all, nothing matching the readiness filter, and
  // nothing matching the search. Collapsing them would tell a user narrowing
  // to Blocked on a healthy project that their project has no tasks.
  if (!filtered.length) {
    if (!tasks.length) {
      return <EmptyState icon={<ClipboardList size={21}/>} title="No execution tasks yet" description={user?.role === "internal_employee" ? "No task is currently assigned to you on this project." : "This project's baseline has no tasks to execute."}/>;
    }
    const filterLabel = readinessFilter === "all" ? null : readinessFilter;
    return <EmptyState
      icon={<ClipboardList size={21}/>}
      title={filterLabel ? `No ${filterLabel} tasks` : "No tasks match this search"}
      description={filterLabel ? `No task on this project is currently ${filterLabel}${term ? " and matches this search" : ""}.` : "Try a different search term."}
    />;
  }

  return <div className="overflow-hidden rounded-2xl border border-slate-200 bg-white" aria-label="Task execution board">
    {filtered.map(task => {
      const expanded = expandedId === task.id;
      return <article key={task.id} className="border-b border-slate-100 last:border-0">
        <button type="button" className="flex w-full flex-wrap items-center gap-3 px-4 py-4 text-left sm:px-5" onClick={() => setExpandedId(expanded ? null : task.id)} aria-expanded={expanded}>
          <span className="font-mono text-xs font-black tracking-wide text-blue-700">{task.original_code}</span>
          <span className="min-w-0 flex-1"><strong className="block truncate text-sm font-black text-slate-950">{task.title}</strong><span className="mt-0.5 block text-xs text-slate-500">{[task.phase, task.category].filter(Boolean).join(" / ") || plannedDayLabel(task)}</span></span>
          {/* U18: only the two COMPUTED states earn a pill. The other seven
              readiness states are defined by the backend as a restatement of
              lifecycle_status, which the status pill on this same row
              already shows - rendering both would put "planned" and
              "Completed" side by side saying one thing twice. */}
          {COMPUTED_READINESS_STATES.includes(task.readiness?.state) && <Pill tone={readinessTone(task.readiness.state)}>{readinessLabel(task.readiness.state)}</Pill>}
          {task.approval?.task_class === "class_a" && <Pill tone="yellow">Class A</Pill>}
          {task.approval?.approval_required && <Pill tone="orange">Approval required</Pill>}
          {task.evidence_required && <Pill tone="violet"><Paperclip size={12}/> Evidence required</Pill>}
          {task.open_blocker_count > 0 && <Pill tone="orange"><ShieldAlert size={12}/> {task.open_blocker_count} blocker{task.open_blocker_count === 1 ? "" : "s"}</Pill>}
          {task.active_support_count > 0 && <Pill tone="blue"><CircleUserRound size={12}/> {task.active_support_count} support</Pill>}
          <Pill tone={STATUS_TONE[task.lifecycle_status] || "gray"}>{task.lifecycle_status.replaceAll("_", " ")}</Pill>
          {expanded ? <ChevronUp size={18} className="text-slate-400"/> : <ChevronDown size={18} className="text-slate-400"/>}
        </button>
        {expanded && <div className="border-t border-slate-100 bg-slate-50/60 px-4 py-4 sm:px-5"><TaskDetailPanel projectId={projectId} task={task} user={user} roles={roles} candidates={candidates} onChanged={load}/></div>}
      </article>;
    })}
  </div>;
}
