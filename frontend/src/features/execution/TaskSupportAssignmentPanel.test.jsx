import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { taskExecutionApi } from "../../api/taskExecutionApi";
import { TaskSupportAssignmentPanel } from "./components/TaskSupportAssignmentPanel";

vi.mock("../../api/taskExecutionApi", () => ({ taskExecutionApi: { assignSupport: vi.fn(), endSupportAssignment: vi.fn() } }));

const task = { id: "t1", task_kind: "work", support_assignments: [] };
// The board now resolves candidates once for the whole project and passes
// them in, so the panel takes them as a prop rather than fetching.
const candidates = [{ id: "m1", employee_id: "e1", name: "Rahul Verma", project_role: "internal_employee" }];

beforeEach(() => {
  vi.clearAllMocks();
});

describe("TaskSupportAssignmentPanel", () => {
  it("lists the internal_employee candidates it is given", async () => {
    render(<TaskSupportAssignmentPanel projectId="p1" task={task} candidates={candidates} canAssign onChanged={vi.fn()}/>);
    const select = screen.getByLabelText("Support employee");
    expect(within(select).queryByText("Rahul Verma")).toBeInTheDocument();
    expect(within(select).queryByText("Anita Rao")).not.toBeInTheDocument();
  });

  it("explains rather than showing the form when the actor cannot assign", () => {
    render(<TaskSupportAssignmentPanel projectId="p1" task={task} candidates={candidates} canAssign={false} onChanged={vi.fn()}/>);
    expect(screen.queryByLabelText("Support employee")).not.toBeInTheDocument();
    expect(screen.getByText(/only this project's supervisor can assign support/i)).toBeInTheDocument();
  });

  it("names the PM as the controller on an approval gate", () => {
    render(<TaskSupportAssignmentPanel projectId="p1" task={{ ...task, task_kind: "approval_gate" }} candidates={candidates} canAssign={false} onChanged={vi.fn()}/>);
    expect(screen.getByText(/only this project's pm can assign follow-up support/i)).toBeInTheDocument();
  });

  it("assigns a support employee and clears the form", async () => {
    taskExecutionApi.assignSupport.mockResolvedValue({});
    const onChanged = vi.fn();
    render(<TaskSupportAssignmentPanel projectId="p1" task={task} candidates={candidates} canAssign onChanged={onChanged}/>);
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
    render(<TaskSupportAssignmentPanel projectId="p1" task={withAssignment} candidates={candidates} canAssign onChanged={onChanged}/>);
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
    render(<TaskSupportAssignmentPanel projectId="p1" task={withAssignment} candidates={candidates} canAssign onChanged={vi.fn()}/>);
    expect(screen.queryByRole("button", { name: "End" })).not.toBeInTheDocument();
  });
});
