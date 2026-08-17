import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { taskExecutionApi } from "../../api/taskExecutionApi";
import { MyAssignedWorkList } from "./components/MyAssignedWorkList";

vi.mock("../../api/taskExecutionApi", () => ({ taskExecutionApi: { list: vi.fn() } }));

const task = (overrides = {}) => ({
  id: "t1", project_id: "p1", baseline_id: "b1", original_code: "T001", template_sequence: 1,
  title: "Install door frames", task_kind: "work", task_class: "standard", lifecycle_status: "ready",
  schedule_classification: "execution", planned_start_day: 1, planned_end_day: 1,
  planned_start_date: "2026-08-19", planned_end_date: "2026-08-19", phase: "Civil", category: "Interiors",
  evidence_required: false, open_blocker_count: 0, active_support_count: 1,
  readiness: { state: "ready", reasons: [], advisories: [] }, variance: null,
  created_at: "2026-08-01T00:00:00Z", updated_at: "2026-08-01T00:00:00Z",
  ...overrides,
});

beforeEach(() => { vi.clearAllMocks(); });

describe("MyAssignedWorkList", () => {
  it("counts tasks into the 5 summary tiles", async () => {
    taskExecutionApi.list.mockResolvedValue([
      task({ id: "t1", lifecycle_status: "ready" }),
      task({ id: "t2", lifecycle_status: "in_progress", readiness: { state: "in_progress", reasons: [], advisories: [] } }),
    ]);
    render(<MyAssignedWorkList projectId="p1" onOpenTask={vi.fn()}/>);
    const group = await screen.findByRole("group", { name: /my work summary/i });
    expect(within(group).getByText("2")).toBeInTheDocument();
  });

  it("filters by status chip", async () => {
    taskExecutionApi.list.mockResolvedValue([
      task({ id: "t1", title: "Install door frames", lifecycle_status: "ready" }),
      task({ id: "t2", title: "Install ceiling", lifecycle_status: "completed", readiness: { state: "completed", reasons: [], advisories: [] } }),
    ]);
    render(<MyAssignedWorkList projectId="p1" onOpenTask={vi.fn()}/>);
    await screen.findByText("Install door frames");
    fireEvent.click(screen.getByRole("button", { name: "Completed" }));
    await waitFor(() => expect(screen.queryByText("Install door frames")).not.toBeInTheDocument());
    expect(screen.getByText("Install ceiling")).toBeInTheDocument();
  });

  it("labels the next action for a ready task as starting work", async () => {
    taskExecutionApi.list.mockResolvedValue([task({ lifecycle_status: "ready" })]);
    render(<MyAssignedWorkList projectId="p1" onOpenTask={vi.fn()}/>);
    expect(await screen.findByText("Start work")).toBeInTheDocument();
  });

  it("labels the next action for an in-progress task as updating progress", async () => {
    taskExecutionApi.list.mockResolvedValue([task({ lifecycle_status: "in_progress" })]);
    render(<MyAssignedWorkList projectId="p1" onOpenTask={vi.fn()}/>);
    expect(await screen.findByText("Update progress")).toBeInTheDocument();
  });

  it("calls onOpenTask with the task id when a row is clicked", async () => {
    const onOpenTask = vi.fn();
    taskExecutionApi.list.mockResolvedValue([task({ id: "t1", title: "Install door frames" })]);
    render(<MyAssignedWorkList projectId="p1" onOpenTask={onOpenTask}/>);
    fireEvent.click(await screen.findByText("Install door frames"));
    expect(onOpenTask).toHaveBeenCalledWith("t1");
  });

  it("shows an empty state when no task is assigned", async () => {
    taskExecutionApi.list.mockResolvedValue([]);
    render(<MyAssignedWorkList projectId="p1" onOpenTask={vi.fn()}/>);
    expect(await screen.findByText("No tasks assigned")).toBeInTheDocument();
  });
});
