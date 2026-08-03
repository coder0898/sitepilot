import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { projectsApi } from "../../api/projectsApi";
import { taskExecutionApi } from "../../api/taskExecutionApi";
import { TaskSupportAssignmentPanel } from "./components/TaskSupportAssignmentPanel";

vi.mock("../../api/projectsApi", () => ({ projectsApi: { detail: vi.fn() } }));
vi.mock("../../api/taskExecutionApi", () => ({ taskExecutionApi: { assignSupport: vi.fn(), endSupportAssignment: vi.fn() } }));

const task = { id: "t1", support_assignments: [] };
const project = {
  id: "p1",
  memberships: [
    { id: "m1", employee_id: "e1", name: "Rahul Verma", project_role: "internal_employee" },
    { id: "m2", employee_id: "e2", name: "Anita Rao", project_role: "site_supervisor" },
  ],
};

beforeEach(() => {
  vi.clearAllMocks();
  projectsApi.detail.mockResolvedValue(project);
});

describe("TaskSupportAssignmentPanel", () => {
  it("lists only active internal_employee members as assignment candidates", async () => {
    render(<TaskSupportAssignmentPanel projectId="p1" task={task} onChanged={vi.fn()}/>);
    await waitFor(() => expect(projectsApi.detail).toHaveBeenCalledWith("p1"));
    const select = screen.getByLabelText("Support employee");
    expect(within(select).queryByText("Rahul Verma")).toBeInTheDocument();
    expect(within(select).queryByText("Anita Rao")).not.toBeInTheDocument();
  });

  it("assigns a support employee and clears the form", async () => {
    taskExecutionApi.assignSupport.mockResolvedValue({});
    const onChanged = vi.fn();
    render(<TaskSupportAssignmentPanel projectId="p1" task={task} onChanged={onChanged}/>);
    await screen.findByText("Rahul Verma");
    fireEvent.change(screen.getByLabelText("Support employee"), { target: { value: "e1" } });
    fireEvent.change(screen.getByLabelText("Responsibility"), { target: { value: "Material handling" } });
    fireEvent.click(screen.getByRole("button", { name: "Assign" }));
    await waitFor(() => expect(taskExecutionApi.assignSupport).toHaveBeenCalledWith("p1", "t1", { employee_id: "e1", responsibility: "Material handling" }));
    await waitFor(() => expect(onChanged).toHaveBeenCalledTimes(1));
  });

  it("ends an active assignment with a required reason code", async () => {
    taskExecutionApi.endSupportAssignment.mockResolvedValue({});
    const withAssignment = { ...task, support_assignments: [{ id: "sa1", status: "active", responsibility: "Material handling" }] };
    const onChanged = vi.fn();
    render(<TaskSupportAssignmentPanel projectId="p1" task={withAssignment} onChanged={onChanged}/>);
    fireEvent.click(screen.getByRole("button", { name: "End" }));
    const confirmButton = screen.getByRole("button", { name: "Confirm" });
    expect(confirmButton).toBeDisabled();
    fireEvent.change(screen.getByLabelText("Reason code"), { target: { value: "reassigned" } });
    expect(confirmButton).toBeEnabled();
    fireEvent.click(confirmButton);
    await waitFor(() => expect(taskExecutionApi.endSupportAssignment).toHaveBeenCalledWith("p1", "t1", "sa1", { reason_code: "reassigned", reason_detail: null }));
    expect(onChanged).toHaveBeenCalledTimes(1);
  });

  it("does not show End for an already-ended assignment", () => {
    const withAssignment = { ...task, support_assignments: [{ id: "sa1", status: "ended", responsibility: "Material handling" }] };
    render(<TaskSupportAssignmentPanel projectId="p1" task={withAssignment} onChanged={vi.fn()}/>);
    expect(screen.queryByRole("button", { name: "End" })).not.toBeInTheDocument();
  });
});
