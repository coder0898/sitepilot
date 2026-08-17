import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { taskExecutionApi } from "../../api/taskExecutionApi";
import { TaskActionView } from "./components/TaskActionView";

vi.mock("../../api/taskExecutionApi", () => ({ taskExecutionApi: {
  detail: vi.fn(), listExternalApprovals: vi.fn(), transitionStatus: vi.fn(), submitProgress: vi.fn(), downloadEvidence: vi.fn(),
  verify: vi.fn(), approve: vi.fn(), logBlocker: vi.fn(), resolveBlocker: vi.fn(), logDelay: vi.fn(),
  assignSupport: vi.fn(), endSupportAssignment: vi.fn(),
} }));

const employee = { id: "u-emp", role: "internal_employee" };

const summaryTask = (overrides = {}) => ({
  id: "t1", original_code: "T031", title: "Install gypsum partition framework",
  lifecycle_status: "in_progress", phase: "Civil", category: "Interiors",
  readiness: { state: "in_progress", reasons: [], advisories: [] }, variance: null,
  ...overrides,
});

const detail = (overrides = {}) => ({
  id: "t1", project_id: "p1", baseline_id: "b1", original_code: "T031", template_sequence: 1,
  title: "Install gypsum partition framework", task_kind: "work", task_class: "standard",
  lifecycle_status: "in_progress", schedule_classification: "execution",
  description: "Frame and board the partition.",
  predecessors: [], progress_updates: [], verifications: [], approvals: [],
  blockers: [], delays: [], support_assignments: [], audit_events: [],
  evidence_required: false, actor_is_assigned_support: true,
  readiness: { state: "in_progress", reasons: [], advisories: [] },
  created_at: "2026-08-01T00:00:00Z", updated_at: "2026-08-01T00:00:00Z",
  ...overrides,
});

beforeEach(() => {
  vi.clearAllMocks();
  taskExecutionApi.listExternalApprovals.mockResolvedValue([]);
});

describe("TaskActionView", () => {
  it("shows the Action Center when the task is running late, with an Update Progress quick action", async () => {
    taskExecutionApi.detail.mockResolvedValue(detail({
      support_assignments: [{ id: "sa1", task_id: "t1", project_id: "p1", employee_id: "e1", responsibility: "Execution", status: "active", starts_at: "2026-08-01T00:00:00Z", ends_at: null, assigned_by: "u1", created_at: "2026-08-01T00:00:00Z" }],
    }));
    render(<TaskActionView projectId="p1" project={null} task={summaryTask({ variance: { status: "late", days: 2 } })} user={employee} candidates={[]} onBack={vi.fn()} onChanged={vi.fn()}/>);
    expect(await screen.findByText("Action Center")).toBeInTheDocument();
    expect(screen.getByText(/running 2 days behind/i)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /update progress/i })).toBeInTheDocument();
  });

  it("hides the Action Center when the task needs no attention", async () => {
    taskExecutionApi.detail.mockResolvedValue(detail({ lifecycle_status: "ready" }));
    render(<TaskActionView projectId="p1" project={null} task={summaryTask({ lifecycle_status: "ready", readiness: { state: "ready", reasons: [], advisories: [] } })} user={employee} candidates={[]} onBack={vi.fn()} onChanged={vi.fn()}/>);
    await screen.findByText("Frame and board the partition.");
    expect(screen.queryByText("Action Center")).not.toBeInTheDocument();
  });

  it("shows the Approvals Pending Quick Info count from the loaded detail", async () => {
    taskExecutionApi.detail.mockResolvedValue(detail({
      predecessors: [{ id: "t0", original_code: "T030", title: "Ceiling framework", lifecycle_status: "completed", task_kind: "work", task_class: "standard", dependency_type: "finish_to_start", blocking: true }],
      readiness: { state: "blocked", reasons: [{ kind: "approval", subject_id: "a1", detail: "Waiting on Fire NOC.", blocking: true }], advisories: [] },
    }));
    render(<TaskActionView projectId="p1" project={null} task={summaryTask()} user={employee} candidates={[]} onBack={vi.fn()} onChanged={vi.fn()}/>);
    await screen.findByText("Frame and board the partition.");
    const stat = screen.getByText("Approvals Pending").closest("section");
    expect(stat).toHaveTextContent("1");
  });

  it("calls onBack when the back button is clicked", async () => {
    taskExecutionApi.detail.mockResolvedValue(detail());
    const onBack = vi.fn();
    render(<TaskActionView projectId="p1" project={null} task={summaryTask()} user={employee} candidates={[]} onBack={onBack} onChanged={vi.fn()}/>);
    await screen.findByText("Frame and board the partition.");
    fireEvent.click(screen.getByRole("button", { name: /back to my assigned work/i }));
    expect(onBack).toHaveBeenCalled();
  });
});
