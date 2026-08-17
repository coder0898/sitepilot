import { AlertTriangle, ClipboardEdit, History, LayoutGrid, Paperclip, SlidersHorizontal, X } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { Button, Pill } from "../../../components/ui";
import { actorProjectRoles, STATUS_TONE, TaskDetailContent } from "./TaskDetailContent";
import { COMPUTED_READINESS_STATES, readinessLabel, readinessTone } from "./TaskReadinessPanel";

const TABS = [
  ["overview", "Overview", LayoutGrid],
  ["actions", "Action Forms", SlidersHorizontal],
  ["activity", "Activity Log", History],
];

const FOOTER_TONE = {
  blue: "text-blue-700", red: "text-rose-700", amber: "text-amber-700", gray: "text-slate-500",
};

function anchorTo(id) {
  document.getElementById(id)?.scrollIntoView?.({ behavior: "smooth", block: "start" });
}

// Right-side overlay drawer for a task's full detail - large, scrolls
// internally, backdrop behind it, page behind locked from scrolling while
// it's open. Shared by the Admin/PM/Super Admin Execution Calendar and the
// Supervisor 3-Day Operations Board. Three tabs only (Overview/Action
// Forms/Activity Log); all business logic (permissions, transitions, forms)
// lives in TaskDetailContent and is only reorganized here, never duplicated.
export function TaskDetailDrawer({ projectId, project, task, user, candidates, onClose, onChanged }) {
  const [activeTab, setActiveTab] = useState("overview");
  // Bumped on every click so re-requesting the SAME kind while the panel is
  // already open still re-triggers TaskBlockerDelayPanel's effect (a plain
  // string prop wouldn't change value on a repeat click).
  const [blockerDelayRequest, setBlockerDelayRequest] = useState(null);
  const [footer, setFooter] = useState(null);

  // The page behind the drawer must not scroll while it's open.
  useEffect(() => {
    if (!task) return undefined;
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => { document.body.style.overflow = previousOverflow; };
  }, [task]);

  useEffect(() => { setActiveTab("overview"); }, [task?.id]);

  // Memoized, not recomputed as a fresh array every render: TaskDetailContent
  // depends on `roles` inside the effect that lifts the footer descriptor up
  // via `onFooterState`/`setFooter` - a new array reference every render
  // would retrigger that effect every time this component re-renders for
  // ANY reason (including the footer state update itself), which is an
  // infinite render loop, not just a wasted recompute.
  const roles = useMemo(() => actorProjectRoles(project, user), [project, user]);

  if (!task) return null;

  function goToActionForms(anchorId) {
    setActiveTab("actions");
    // The Action Forms pane only exists in the DOM once this tab is active,
    // so the scroll has to wait a tick for it to mount.
    requestAnimationFrame(() => anchorTo(anchorId));
  }

  function requestBlockerDelay() {
    setBlockerDelayRequest({ kind: "blocker", nonce: Date.now() });
    goToActionForms("action-blockers-delays");
  }

  return <>
    <div className="fixed inset-0 z-40 bg-slate-950/40" onClick={onClose} aria-hidden="true"/>
    <aside
      className="fixed inset-y-0 right-0 z-50 flex w-full max-w-[90vw] flex-col rounded-l-2xl bg-white shadow-[-16px_0_50px_rgba(15,23,42,.18)] sm:w-[820px]"
      aria-label={`Task detail - ${task.original_code}`}
    >
      <header className="flex items-start justify-between gap-3 border-b border-slate-200 px-6 py-5">
        <div className="min-w-0">
          <span className="font-mono text-xs font-black text-blue-700">{task.original_code}</span>
          <h2 className="mt-0.5 text-lg font-black leading-snug text-slate-950">{task.title}</h2>
          <p className="mt-0.5 text-xs font-bold text-slate-500">{[task.phase, task.category].filter(Boolean).join(" / ") || "Unphased"}</p>
          <div className="mt-2 flex flex-wrap items-center gap-1.5">
            <Pill tone={STATUS_TONE[task.lifecycle_status] || "gray"}>{task.lifecycle_status.replaceAll("_", " ")}</Pill>
            {COMPUTED_READINESS_STATES.includes(task.readiness?.state) && <Pill tone={readinessTone(task.readiness.state)}>{readinessLabel(task.readiness.state)}</Pill>}
          </div>
        </div>
        <button type="button" aria-label="Close task detail" onClick={onClose} className="shrink-0 rounded-lg p-1.5 text-slate-400 transition hover:bg-slate-100 hover:text-slate-700">
          <X size={20}/>
        </button>
      </header>

      {/* Quick Actions: each switches to Action Forms and anchor-scrolls into
          the one real section inside TaskDetailContent, rather than
          duplicating any transition/form logic. */}
      <div className="flex flex-wrap gap-2 border-b border-slate-100 px-6 py-3">
        <Button size="sm" variant="secondary" onClick={() => goToActionForms("action-progress")}><ClipboardEdit size={14}/> Update Progress</Button>
        <Button size="sm" variant="secondary" onClick={() => goToActionForms("action-progress")}><Paperclip size={14}/> Add Evidence</Button>
        <Button size="sm" variant="secondary" onClick={requestBlockerDelay}><AlertTriangle size={14}/> Report Delay / Blocker</Button>
      </div>

      <nav className="flex gap-1 border-b border-slate-200 px-6" aria-label="Task detail tabs">
        {TABS.map(([key, label, Icon]) => (
          <button
            key={key}
            type="button"
            aria-current={activeTab === key ? "true" : undefined}
            onClick={() => setActiveTab(key)}
            className={`flex items-center gap-1.5 border-b-2 px-3 py-3 text-sm font-bold transition ${activeTab === key ? "border-blue-600 text-blue-700" : "border-transparent text-slate-500 hover:text-slate-800"}`}
          ><Icon size={15}/> {label}</button>
        ))}
      </nav>

      <div className="min-h-0 flex-1 overflow-y-auto bg-slate-50/60 px-6 py-5">
        <TaskDetailContent
          projectId={projectId}
          project={project}
          task={task}
          user={user}
          roles={roles}
          candidates={candidates}
          onChanged={onChanged}
          autoOpenBlockerDelay={blockerDelayRequest?.kind}
          onFooterState={setFooter}
          activeTab={activeTab}
        />
      </div>

      {footer && <footer className="flex flex-wrap items-center justify-between gap-3 border-t border-slate-200 bg-white px-6 py-4">
        <span className={`text-sm font-bold ${FOOTER_TONE[footer.tone] || FOOTER_TONE.gray}`}>{footer.helpText}</span>
        <div className="flex items-center gap-2">
          {footer.secondary && <Button variant="secondary" onClick={footer.secondary.onClick} disabled={footer.secondary.disabled} loading={footer.secondary.loading}>{footer.secondary.label}</Button>}
          {footer.primary && <Button onClick={footer.primary.onClick} disabled={footer.primary.disabled} loading={footer.primary.loading}>{footer.primary.label}</Button>}
        </div>
      </footer>}
    </aside>
  </>;
}
