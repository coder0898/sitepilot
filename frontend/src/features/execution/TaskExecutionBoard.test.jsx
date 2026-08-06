import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { projectsApi } from "../../api/projectsApi";
import { taskExecutionApi } from "../../api/taskExecutionApi";
import { TaskExecutionBoard } from "./components/TaskExecutionBoard";

vi.mock("../../api/taskExecutionApi", () => ({ taskExecutionApi: {
  list: vi.fn(), detail: vi.fn(), transitionStatus: vi.fn(), submitProgress: vi.fn(), downloadEvidence: vi.fn(),
  verify: vi.fn(), approve: vi.fn(), logBlocker: vi.fn(), resolveBlocker: vi.fn(), logDelay: vi.fn(),
  assignSupport: vi.fn(), endSupportAssignment: vi.fn(),
} }));
vi.mock("../../api/projectsApi", () => ({ projectsApi: { detail: vi.fn() } }));

const baseTask = {
  id: "t1", project_id: "p1", baseline_id: "b1", original_code: "T001", template_sequence: 1,
  title: "Mobilise site", task_kind: "work", task_class: "standard", lifecycle_status: "planned",
  schedule_classification: "execution", planned_start_day: 1, planned_end_day: 1, phase: "Setup",
  category: "Site", evidence_required: false, open_blocker_count: 0, active_support_count: 0,
  created_at: "2026-08-01T00:00:00Z", updated_at: "2026-08-01T00:00:00Z",
};
const tasks = [
  baseTask,
  { ...baseTask, id: "t2", original_code: "T002", title: "Survey boundary", lifecycle_status: "in_progress", open_blocker_count: 1, active_support_count: 1 },
];
const detail = {
  ...baseTask,
  description: "Set up the site office and hoarding.",
  predecessors: [],
  progress_updates: [], verifications: [], approvals: [], blockers: [], delays: [], support_assignments: [],
  audit_events: [],
};

beforeEach(() => {
  vi.clearAllMocks();
  taskExecutionApi.list.mockResolvedValue(tasks);
  taskExecutionApi.detail.mockResolvedValue(detail);
  projectsApi.detail.mockResolvedValue({ id: "p1", memberships: [] });
});

describe("TaskExecutionBoard", () => {
  it("renders every task with its live status and summary badges", async () => {
    render(<TaskExecutionBoard projectId="p1" user={{ role: "supervisor" }}/>);
    expect(await screen.findByText("Mobilise site")).toBeInTheDocument();
    expect(screen.getByText("Survey boundary")).toBeInTheDocument();
    expect(screen.getByText("planned")).toBeInTheDocument();
    expect(screen.getByText("in progress")).toBeInTheDocument();
    expect(screen.getByText("1 blocker")).toBeInTheDocument();
    expect(screen.getByText("1 support")).toBeInTheDocument();
  });

  it("filters rows by the search prop", async () => {
    render(<TaskExecutionBoard projectId="p1" user={{ role: "supervisor" }} search="survey"/>);
    await waitFor(() => expect(screen.queryByText("Mobilise site")).not.toBeInTheDocument());
    expect(screen.getByText("Survey boundary")).toBeInTheDocument();
  });

  it("expands a row to load and show its detail", async () => {
    render(<TaskExecutionBoard projectId="p1" user={{ role: "supervisor" }}/>);
    fireEvent.click(await screen.findByRole("button", { name: /mobilise site/i }));
    expect(await screen.findByText("Set up the site office and hoarding.")).toBeInTheDocument();
    expect(taskExecutionApi.detail).toHaveBeenCalledWith("p1", "t1");
  });

  it("shows the valid forward transition for a Supervisor and advances it on click", async () => {
    taskExecutionApi.transitionStatus.mockResolvedValue({ ...detail, lifecycle_status: "ready" });
    render(<TaskExecutionBoard projectId="p1" user={{ role: "supervisor" }}/>);
    fireEvent.click(await screen.findByRole("button", { name: /mobilise site/i }));
    await screen.findByText("Set up the site office and hoarding.");
    fireEvent.click(screen.getByRole("button", { name: "Mark ready" }));
    await waitFor(() => expect(taskExecutionApi.transitionStatus).toHaveBeenCalledWith("p1", "t1", { target_status: "ready" }));
    await waitFor(() => expect(taskExecutionApi.list).toHaveBeenCalledTimes(2));
  });

  it("hides status transition controls for a role the backend would reject", async () => {
    render(<TaskExecutionBoard projectId="p1" user={{ role: "internal_employee" }}/>);
    fireEvent.click(await screen.findByRole("button", { name: /mobilise site/i }));
    await screen.findByText("Set up the site office and hoarding.");
    expect(screen.queryByRole("button", { name: "Mark ready" })).not.toBeInTheDocument();
  });

  it("lets the assigned Internal Employee start and submit their task", async () => {
    taskExecutionApi.detail.mockResolvedValue({
      ...detail, lifecycle_status: "ready", actor_is_assigned_support: true,
      support_assignments: [{ id: "sa1", task_id: "t1", project_id: "p1", employee_id: "e1", responsibility: "Execution", status: "active", starts_at: "2026-08-01T00:00:00Z", ends_at: null, assigned_by: "u1", created_at: "2026-08-01T00:00:00Z" }],
    });
    render(<TaskExecutionBoard projectId="p1" user={{ role: "internal_employee" }}/>);
    fireEvent.click(await screen.findByRole("button", { name: /mobilise site/i }));
    await screen.findByText("Set up the site office and hoarding.");
    expect(screen.getByRole("button", { name: "Start work" })).toBeInTheDocument();
  });

  it("hides start/submit from an Internal Employee who is not the one assigned", async () => {
    taskExecutionApi.detail.mockResolvedValue({
      ...detail, lifecycle_status: "ready", actor_is_assigned_support: false,
      support_assignments: [{ id: "sa1", task_id: "t1", project_id: "p1", employee_id: "someone-else", responsibility: "Execution", status: "active", starts_at: "2026-08-01T00:00:00Z", ends_at: null, assigned_by: "u1", created_at: "2026-08-01T00:00:00Z" }],
    });
    render(<TaskExecutionBoard projectId="p1" user={{ role: "internal_employee" }}/>);
    fireEvent.click(await screen.findByRole("button", { name: /mobilise site/i }));
    await screen.findByText("Set up the site office and hoarding.");
    expect(screen.queryByRole("button", { name: "Start work" })).not.toBeInTheDocument();
  });

  it("hides start/submit from the Supervisor once an Internal Employee is assigned", async () => {
    taskExecutionApi.detail.mockResolvedValue({
      ...detail, lifecycle_status: "ready", actor_is_assigned_support: false,
      support_assignments: [{ id: "sa1", task_id: "t1", project_id: "p1", employee_id: "e1", responsibility: "Execution", status: "active", starts_at: "2026-08-01T00:00:00Z", ends_at: null, assigned_by: "u1", created_at: "2026-08-01T00:00:00Z" }],
    });
    render(<TaskExecutionBoard projectId="p1" user={{ role: "supervisor" }}/>);
    fireEvent.click(await screen.findByRole("button", { name: /mobilise site/i }));
    await screen.findByText("Set up the site office and hoarding.");
    expect(screen.queryByRole("button", { name: "Start work" })).not.toBeInTheDocument();
  });

  it("requires a reason before cancelling a task", async () => {
    render(<TaskExecutionBoard projectId="p1" user={{ role: "admin" }}/>);
    fireEvent.click(await screen.findByRole("button", { name: /mobilise site/i }));
    await screen.findByText("Set up the site office and hoarding.");
    const cancelButton = screen.getByRole("button", { name: "Cancel task" });
    expect(cancelButton).toBeDisabled();
    fireEvent.change(screen.getByPlaceholderText(/reason for cancellation/i), { target: { value: "Scope dropped." } });
    expect(cancelButton).toBeEnabled();
    fireEvent.click(cancelButton);
    await waitFor(() => expect(taskExecutionApi.transitionStatus).toHaveBeenCalledWith("p1", "t1", { target_status: "cancelled", reason: "Scope dropped." }));
  });

  it("mounts the progress form only while the task is in_progress", async () => {
    taskExecutionApi.detail.mockResolvedValue({ ...detail, lifecycle_status: "in_progress" });
    render(<TaskExecutionBoard projectId="p1" user={{ role: "supervisor" }}/>);
    fireEvent.click(await screen.findByRole("button", { name: /mobilise site/i }));
    expect(await screen.findByText("Log progress")).toBeInTheDocument();
  });

  it("hides the progress form when the task is not in_progress", async () => {
    render(<TaskExecutionBoard projectId="p1" user={{ role: "supervisor" }}/>);
    fireEvent.click(await screen.findByRole("button", { name: /mobilise site/i }));
    await screen.findByText("Set up the site office and hoarding.");
    expect(screen.queryByText("Log progress")).not.toBeInTheDocument();
  });

  it("hides the progress form from the Supervisor once an Internal Employee is assigned and actively executing", async () => {
    taskExecutionApi.detail.mockResolvedValue({
      ...detail, lifecycle_status: "in_progress", actor_is_assigned_support: false,
      support_assignments: [{ id: "sa1", task_id: "t1", project_id: "p1", employee_id: "e1", responsibility: "Execution", status: "active", starts_at: "2026-08-01T00:00:00Z", ends_at: null, assigned_by: "u1", created_at: "2026-08-01T00:00:00Z" }],
    });
    render(<TaskExecutionBoard projectId="p1" user={{ role: "supervisor" }}/>);
    fireEvent.click(await screen.findByRole("button", { name: /mobilise site/i }));
    await screen.findByText("Set up the site office and hoarding.");
    expect(screen.queryByText("Log progress")).not.toBeInTheDocument();
  });

  it("shows the progress form to the assigned Internal Employee", async () => {
    taskExecutionApi.detail.mockResolvedValue({
      ...detail, lifecycle_status: "in_progress", actor_is_assigned_support: true,
      support_assignments: [{ id: "sa1", task_id: "t1", project_id: "p1", employee_id: "e1", responsibility: "Execution", status: "active", starts_at: "2026-08-01T00:00:00Z", ends_at: null, assigned_by: "u1", created_at: "2026-08-01T00:00:00Z" }],
    });
    render(<TaskExecutionBoard projectId="p1" user={{ role: "internal_employee" }}/>);
    fireEvent.click(await screen.findByRole("button", { name: /mobilise site/i }));
    expect(await screen.findByText("Log progress")).toBeInTheDocument();
  });

  it("mounts the decision controls for a role that can drive transitions", async () => {
    taskExecutionApi.detail.mockResolvedValue({ ...detail, task_kind: "work", task_class: "standard", lifecycle_status: "submitted" });
    render(<TaskExecutionBoard projectId="p1" user={{ role: "supervisor" }}/>);
    fireEvent.click(await screen.findByRole("button", { name: /mobilise site/i }));
    expect(await screen.findByText("Supervisor verification")).toBeInTheDocument();
  });

  it("hides the decision controls for a role that cannot drive transitions", async () => {
    taskExecutionApi.detail.mockResolvedValue({ ...detail, task_kind: "work", task_class: "standard", lifecycle_status: "submitted" });
    render(<TaskExecutionBoard projectId="p1" user={{ role: "internal_employee" }}/>);
    fireEvent.click(await screen.findByRole("button", { name: /mobilise site/i }));
    await waitFor(() => expect(taskExecutionApi.detail).toHaveBeenCalled());
    expect(screen.queryByText("Supervisor verification")).not.toBeInTheDocument();
  });

  it("shows a read-only completed summary and hides execution controls once a task is completed", async () => {
    taskExecutionApi.detail.mockResolvedValue({
      ...detail,
      lifecycle_status: "completed",
      task_class: "class_a",
      progress_updates: [{ id: "pu1", task_id: "t1", project_id: "p1", update_type: "evidence", status_claim: null, note: "Done.", submitted_by: "u1", source: "portal", created_at: "2026-08-01T00:00:00Z", evidence: [{ id: "e1", file_id: "f1", evidence_type: "photo", caption: null, original_filename: "site.jpg", mime_type: "image/jpeg", size_bytes: 100 }] }],
      approvals: [{ id: "a1", verification_id: "v1", decision: "approved", remarks: "Looks good.", decided_by: "u2", decided_by_name: "Priya PM", decided_at: "2026-08-02T00:00:00Z" }],
      audit_events: [{ id: "ev1", action: "TASK_STATUS_CHANGED", source: "portal", before_status: "approval_pending", after_status: "completed", reason: "Approved by PM.", actor_user_id: "u2", actor_name: "Priya PM", occurred_at: "2026-08-02T00:00:00Z" }],
    });
    render(<TaskExecutionBoard projectId="p1" user={{ role: "supervisor" }}/>);
    fireEvent.click(await screen.findByRole("button", { name: /mobilise site/i }));
    expect(await screen.findByText("Completed")).toBeInTheDocument();
    expect(screen.getAllByText(/priya pm/i).length).toBeGreaterThan(0);
    expect(screen.getByText("site.jpg")).toBeInTheDocument();

    expect(screen.queryByRole("button", { name: /report blocker/i })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /report delay/i })).not.toBeInTheDocument();
    expect(screen.queryByText("Support assignments")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Cancel task" })).not.toBeInTheDocument();
    expect(screen.queryByText("Log progress")).not.toBeInTheDocument();
  });

  it("shows a read-only cancelled summary with reason and actor, and hides execution controls", async () => {
    taskExecutionApi.detail.mockResolvedValue({
      ...detail,
      lifecycle_status: "cancelled",
      audit_events: [{ id: "ev1", action: "TASK_STATUS_CHANGED", source: "portal", before_status: "planned", after_status: "cancelled", reason: "Scope removed by client.", actor_user_id: "u3", actor_name: "Admin User", occurred_at: "2026-08-03T00:00:00Z" }],
    });
    render(<TaskExecutionBoard projectId="p1" user={{ role: "admin" }}/>);
    fireEvent.click(await screen.findByRole("button", { name: /mobilise site/i }));
    expect((await screen.findAllByText("Cancelled")).length).toBeGreaterThan(0);
    expect(screen.getByText("Scope removed by client.")).toBeInTheDocument();
    expect(screen.getAllByText("Admin User").length).toBeGreaterThan(0);

    expect(screen.queryByRole("button", { name: /report blocker/i })).not.toBeInTheDocument();
    expect(screen.queryByText("Support assignments")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Cancel task" })).not.toBeInTheDocument();
  });

  it("still shows execution controls for a rejected task, since rejected is not terminal", async () => {
    taskExecutionApi.detail.mockResolvedValue({ ...detail, lifecycle_status: "rejected" });
    render(<TaskExecutionBoard projectId="p1" user={{ role: "supervisor" }}/>);
    fireEvent.click(await screen.findByRole("button", { name: /mobilise site/i }));
    await screen.findByRole("button", { name: /report blocker/i });
    expect(screen.getByText("Support assignments")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Start work" })).toBeInTheDocument();
  });

  it("shows history sections in the expanded detail", async () => {
    taskExecutionApi.detail.mockResolvedValue({
      ...detail,
      predecessors: [{ id: "t0", original_code: "T000", title: "Handover", lifecycle_status: "completed", task_kind: "work", task_class: "standard", dependency_type: "finish_to_start", blocking: true }],
      progress_updates: [{ id: "pu1", task_id: "t1", project_id: "p1", update_type: "note", status_claim: null, note: "Crew on site.", submitted_by: "u1", source: "portal", created_at: "2026-08-01T00:00:00Z", evidence: [] }],
      verifications: [{ id: "v1", decision: "verified", remarks: null, verified_by: "u1", verified_at: "2026-08-01T00:00:00Z" }],
      blockers: [{ id: "b1", task_id: "t1", project_id: "p1", type: "material", description: "Waiting on cement.", owner_employee_id: null, started_at: "2026-08-01T00:00:00Z", resolved_at: null, resolved_by: null, created_at: "2026-08-01T00:00:00Z" }],
    });
    render(<TaskExecutionBoard projectId="p1" user={{ role: "supervisor" }}/>);
    fireEvent.click(await screen.findByRole("button", { name: /mobilise site/i }));
    expect(await screen.findByText("Predecessors")).toBeInTheDocument();
    expect(screen.getByText("Handover")).toBeInTheDocument();
    expect(screen.getByText("Crew on site.")).toBeInTheDocument();
    expect(screen.getByText("Waiting on cement.")).toBeInTheDocument();
  });

  it("mounts the support assignment panel in the expanded detail", async () => {
    projectsApi.detail.mockResolvedValue({ id: "p1", memberships: [{ id: "m1", employee_id: "e1", name: "Rahul Verma", project_role: "internal_employee" }] });
    render(<TaskExecutionBoard projectId="p1" user={{ role: "supervisor" }}/>);
    fireEvent.click(await screen.findByRole("button", { name: /mobilise site/i }));
    expect(await screen.findByText("Support assignments")).toBeInTheDocument();
    expect(await screen.findByText("Rahul Verma")).toBeInTheDocument();
  });

  it("discards a stale response from a project switched away from before it resolved", async () => {
    let resolveA;
    const projectATasks = new Promise(resolve => { resolveA = resolve; });
    taskExecutionApi.list.mockImplementationOnce(() => projectATasks);
    const { rerender } = render(<TaskExecutionBoard projectId="pA" user={{ role: "supervisor" }}/>);

    const projectBTasks = [{ ...baseTask, id: "tB", original_code: "TB01", title: "Project B task" }];
    taskExecutionApi.list.mockResolvedValueOnce(projectBTasks);
    rerender(<TaskExecutionBoard projectId="pB" user={{ role: "supervisor" }}/>);
    expect(await screen.findByText("Project B task")).toBeInTheDocument();

    resolveA(tasks); // Project A's slow response resolves after B already rendered
    await new Promise(resolve => setTimeout(resolve, 0));
    expect(screen.getByText("Project B task")).toBeInTheDocument();
    expect(screen.queryByText("Mobilise site")).not.toBeInTheDocument();
  });

  it("covers loading, empty and error/retry states", async () => {
    let resolveList;
    taskExecutionApi.list.mockReturnValueOnce(new Promise(resolve => { resolveList = resolve; }));
    render(<TaskExecutionBoard projectId="p1" user={{ role: "supervisor" }}/>);
    expect(screen.getByText(/loading task execution board/i)).toBeInTheDocument();
    resolveList([]);
    expect(await screen.findByText("No execution tasks yet")).toBeInTheDocument();

    taskExecutionApi.list.mockRejectedValueOnce(new Error("Server unavailable")).mockResolvedValueOnce(tasks);
    const { rerender } = render(<div/>);
    rerender(<TaskExecutionBoard projectId="p2" user={{ role: "supervisor" }}/>);
    expect(await screen.findByText("Server unavailable")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /retry/i }));
    await waitFor(() => expect(screen.getByText("Mobilise site")).toBeInTheDocument());
  });
});
