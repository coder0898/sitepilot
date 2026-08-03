import { ChevronDown, ChevronUp, CircleUserRound, ClipboardList, GitBranch, RefreshCw, ShieldAlert } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { taskExecutionApi } from "../../../api/taskExecutionApi";
import { Button, EmptyState, LoadingSpinner, Pill } from "../../../components/ui";
import { TaskBlockerDelayPanel } from "./TaskBlockerDelayPanel";
import { TaskDecisionModal } from "./TaskDecisionModal";
import { TaskProgressForm } from "./TaskProgressForm";
import { TaskSupportAssignmentPanel } from "./TaskSupportAssignmentPanel";

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

function canDriveTransitions(user) {
  return ["supervisor", "project_manager", "admin", "super_admin"].includes(user?.role);
}
function canCancel(user) {
  return ["project_manager", "admin", "super_admin"].includes(user?.role);
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

  const forwardTargets = canDriveTransitions(user) ? (FORWARD_TRANSITIONS[detail.lifecycle_status] || []) : [];
  const showCancel = canCancel(user) && CANCELLABLE_STATUSES.includes(detail.lifecycle_status);

  return <div className="grid gap-4">
    {error && <div className="rounded-xl border border-rose-200 bg-rose-50 p-3 text-sm font-bold text-rose-700">{error}</div>}
    {detail.description && <p className="text-sm leading-6 text-slate-600">{detail.description}</p>}

    {detail.predecessors.length > 0 && <section className="rounded-xl border border-slate-200 bg-slate-50 p-4">
      <h4 className="flex items-center gap-2 text-xs font-black uppercase tracking-wide text-slate-500"><GitBranch size={14}/> Predecessors</h4>
      <div className="mt-2 grid gap-2">{detail.predecessors.map(dep => <div key={dep.id} className="flex flex-wrap items-center gap-2 text-sm"><span className="font-mono text-xs font-black text-blue-700">{dep.original_code}</span><span className="text-slate-700">{dep.title}</span><Pill tone={STATUS_TONE[dep.lifecycle_status] || "gray"}>{dep.lifecycle_status}</Pill>{dep.blocking && <span className="text-[10px] font-bold text-amber-700">Blocking</span>}</div>)}</div>
    </section>}

    {(forwardTargets.length > 0 || showCancel) && <section className="rounded-xl border border-blue-200 bg-blue-50 p-4">
      <h4 className="text-xs font-black uppercase tracking-wide text-blue-700">Status</h4>
      <div className="mt-2 flex flex-wrap items-center gap-2">
        {forwardTargets.map(target => <Button key={target} size="sm" loading={transitioning === target} onClick={() => transition(target)}>{TRANSITION_LABEL[target] || target}</Button>)}
      </div>
      {showCancel && <div className="mt-3 border-t border-blue-100 pt-3"><CancelControl projectId={projectId} task={detail} onChanged={refreshAll}/></div>}
    </section>}

    {canDriveTransitions(user) && <TaskDecisionModal projectId={projectId} task={detail} onDecided={refreshAll}/>}

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
        {detail.verifications.map(v => <div key={v.id} className="flex flex-wrap items-center gap-2 text-sm"><Pill tone={v.decision === "verified" ? "green" : "red"}>{v.decision}</Pill><span className="text-slate-600">Verified · {new Date(v.verified_at).toLocaleString("en-GB")}</span>{v.remarks && <span className="text-slate-500">- {v.remarks}</span>}</div>)}
        {detail.approvals.map(a => <div key={a.id} className="flex flex-wrap items-center gap-2 text-sm"><Pill tone={a.decision === "approved" ? "green" : "red"}>{a.decision}</Pill><span className="text-slate-600">Approved · {new Date(a.decided_at).toLocaleString("en-GB")}</span>{a.remarks && <span className="text-slate-500">- {a.remarks}</span>}</div>)}
      </div>
    </section>}

    {/* U5: blockers/delays are independent of lifecycle_status, so this
        panel (log form + history + resolve) is always visible, not gated
        by task state or role - any active project member may log one. */}
    <TaskBlockerDelayPanel projectId={projectId} task={detail} onChanged={refreshAll}/>

    <TaskSupportAssignmentPanel projectId={projectId} task={detail} onChanged={refreshAll}/>
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
  if (!filtered.length) return <EmptyState icon={<ClipboardList size={21}/>} title={tasks.length ? "No tasks match this search" : "No execution tasks yet"} description={tasks.length ? "Try a different search term." : "This project's baseline has no tasks to execute."}/>;

  return <div className="overflow-hidden rounded-2xl border border-slate-200 bg-white" aria-label="Task execution board">
    {filtered.map(task => {
      const expanded = expandedId === task.id;
      return <article key={task.id} className="border-b border-slate-100 last:border-0">
        <button type="button" className="flex w-full flex-wrap items-center gap-3 px-4 py-4 text-left sm:px-5" onClick={() => setExpandedId(expanded ? null : task.id)} aria-expanded={expanded}>
          <span className="font-mono text-xs font-black tracking-wide text-blue-700">{task.original_code}</span>
          <span className="min-w-0 flex-1"><strong className="block truncate text-sm font-black text-slate-950">{task.title}</strong><span className="mt-0.5 block text-xs text-slate-500">{[task.phase, task.category].filter(Boolean).join(" / ") || plannedDayLabel(task)}</span></span>
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
