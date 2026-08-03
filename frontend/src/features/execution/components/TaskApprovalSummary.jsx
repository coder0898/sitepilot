import { ChevronDown, ShieldCheck, Stamp } from "lucide-react";
import { Pill } from "../../../components/ui";

// Human copy for the structured approval metadata the backend now derives
// (task_kind/task_class/lifecycle_status -> verification_required,
// approval_required, approver_role, approval_summary, approval_status) -
// see backend/app/services/task_approval_metadata.py. Only "standard" and
// "class_a" task classes exist per the PRD/MVP scope (no Class B/C, no
// distinct Admin-approval class - Admin is only ever an audited fallback).
const CLASS_LABEL = { class_a: "Class A", standard: "Standard" };

const SUMMARY_LABEL = {
  not_required: "Not required",
  supervisor_verification: "Supervisor verification",
  supervisor_and_pm: "Supervisor + PM",
  pm_approval: "PM approval",
};

const STATE_LABEL = {
  not_required: "Not required",
  not_started: "Not started",
  awaiting_verification: "Awaiting verification",
  awaiting_pm_approval: "Awaiting PM approval",
  approved: "Approved",
  rejected: "Rejected",
  cancelled: "Cancelled",
};

const STATE_TONE = {
  not_required: "gray",
  not_started: "gray",
  awaiting_verification: "orange",
  awaiting_pm_approval: "orange",
  approved: "green",
  rejected: "red",
  cancelled: "gray",
};

const WHY_TEXT = {
  not_required: "This task kind completes without a verification or approval decision.",
  supervisor_verification: "This is standard work: the Supervisor verifies it and it completes immediately. No PM approval is required.",
  supervisor_and_pm: "This is Class A work: the Supervisor must verify it, then the Project Manager must approve it, before it completes. Dependent tasks stay blocked until that PM approval.",
  pm_approval: "This is an approval gate: it skips Supervisor verification and completes only once the Project Manager approves it. Dependent tasks stay blocked until then.",
};

export function TaskApprovalSummary({ task }) {
  const approval = task.approval;
  if (!approval) return null;

  const classLabel = CLASS_LABEL[approval.task_class] || null;

  return <section className="rounded-xl border border-slate-200 bg-white px-4 py-3">
    <div className="flex flex-wrap items-center gap-1.5">
      {classLabel && <Pill tone={approval.task_class === "class_a" ? "yellow" : "gray"}>{classLabel}</Pill>}
      <Pill tone={approval.approval_required ? "orange" : "gray"}>{approval.approval_required ? "Approval required" : "No approval required"}</Pill>
      {approval.verification_required && <Pill tone="blue" className="gap-1"><ShieldCheck size={12}/> Supervisor verification</Pill>}
      {approval.approval_required && <Pill tone="yellow" className="gap-1"><Stamp size={12}/> PM approval</Pill>}
      <Pill tone={STATE_TONE[approval.approval_status] || "gray"}>{STATE_LABEL[approval.approval_status] || approval.approval_status}</Pill>
    </div>
    <p className="mt-1.5 text-xs font-bold text-slate-500">Approval: {SUMMARY_LABEL[approval.approval_summary] || approval.approval_summary}</p>
    <details className="group mt-1.5">
      <summary className="flex w-fit cursor-pointer list-none items-center gap-1 text-xs font-bold text-blue-700">
        Why? <ChevronDown size={13} className="transition group-open:rotate-180"/>
      </summary>
      <p className="mt-1.5 max-w-prose text-xs leading-5 text-slate-600">
        {WHY_TEXT[approval.approval_summary] || "No approval rule applies to this task."}
        {approval.blocks_dependents_until_approved && " Dependent tasks cannot start until this decision is recorded."}
      </p>
    </details>
  </section>;
}
