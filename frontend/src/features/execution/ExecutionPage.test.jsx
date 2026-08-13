import { render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { projectsApi } from "../../api/projectsApi";
import { taskExecutionApi } from "../../api/taskExecutionApi";
import { ExecutionPage } from "./ExecutionPage";

vi.mock("../../api/projectsApi", () => ({ projectsApi: {
  detail: vi.fn(),
  list: vi.fn(), executionTasks: vi.fn(), dependencies: vi.fn(), externalGates: vi.fn(), detail: vi.fn(),
} }));
vi.mock("../../api/taskExecutionApi", () => ({ taskExecutionApi: {
  list: vi.fn(), detail: vi.fn(),
} }));

const activeProjects = [{ id: "p1", name: "Sample Fitout Project", code: "P1", status: "active" }];
const assignedTask = {
  id: "t1", project_id: "p1", baseline_id: "b1", original_code: "T001", template_sequence: 1,
  title: "Freeze approved architectural layout", task_kind: "work", task_class: "standard", lifecycle_status: "in_progress",
  schedule_classification: "execution", planned_start_day: 1, planned_end_day: 1, phase: "Design",
  category: "Planning", evidence_required: false, open_blocker_count: 0, active_support_count: 1,
  created_at: "2026-08-05T00:00:00Z", updated_at: "2026-08-05T00:00:00Z",
};

beforeEach(() => {
  vi.clearAllMocks();
  projectsApi.list.mockResolvedValue(activeProjects);
  // The board resolves the actor's authority from the project's active
  // memberships, so every render needs this even when the test is about
  // something else.
  projectsApi.detail.mockResolvedValue({ id: "p1", memberships: [] });
  projectsApi.executionTasks.mockResolvedValue({
    project_id: "p1", project_name: "Sample Fitout Project", total_tasks: 42, included_task_count: 40, excluded_task_count: 2, tasks: [],
  });
  projectsApi.dependencies.mockResolvedValue({ items: [], total: 12, excluded_warning_count: 0 });
  projectsApi.externalGates.mockResolvedValue([]);
  taskExecutionApi.list.mockResolvedValue([assignedTask]);
});

describe("ExecutionPage - Internal Employee scoping", () => {
  it("does not fetch the whole-project baseline/dependencies/gates for an Internal Employee", async () => {
    render(<ExecutionPage user={{ role: "internal_employee", id: "u-ie" }}/>);
    expect(await screen.findByText("Freeze approved architectural layout")).toBeInTheDocument();
    expect(projectsApi.executionTasks).not.toHaveBeenCalled();
    expect(projectsApi.dependencies).not.toHaveBeenCalled();
    expect(projectsApi.externalGates).not.toHaveBeenCalled();
  });

  it("shows the project name from the project list, not from the (skipped) whole-project fetch", async () => {
    render(<ExecutionPage user={{ role: "internal_employee", id: "u-ie" }}/>);
    expect(await screen.findByText("Sample Fitout Project")).toBeInTheDocument();
    expect(screen.getByText("Your assigned tasks")).toBeInTheDocument();
  });

  it("hides the whole-project metric cards and the Dependencies/External Approvals sub-tabs", async () => {
    render(<ExecutionPage user={{ role: "internal_employee", id: "u-ie" }}/>);
    await screen.findByText("Freeze approved architectural layout");
    expect(screen.queryByText("Total tasks")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /dependencies/i })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /external approvals/i })).not.toBeInTheDocument();
  });

  it("still shows the full whole-project view for a Supervisor", async () => {
    render(<ExecutionPage user={{ role: "supervisor", id: "u-sup" }}/>);
    await waitFor(() => expect(projectsApi.executionTasks).toHaveBeenCalledWith("p1"));
    expect(await screen.findByText("Total tasks")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /dependencies/i })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /external approvals/i })).toBeInTheDocument();
  });
});
