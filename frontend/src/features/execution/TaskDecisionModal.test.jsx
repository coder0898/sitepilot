import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { taskExecutionApi } from "../../api/taskExecutionApi";
import { TaskDecisionModal } from "./components/TaskDecisionModal";

vi.mock("../../api/taskExecutionApi", () => ({ taskExecutionApi: { verify: vi.fn(), approve: vi.fn() } }));

const workTask = { id: "t1", original_code: "T001", title: "Mobilise site", task_kind: "work", task_class: "standard", lifecycle_status: "submitted" };
const classATask = { ...workTask, task_class: "class_a", lifecycle_status: "verified" };
const gateTask = { id: "t2", original_code: "T010", title: "Fire NOC", task_kind: "approval_gate", task_class: null, lifecycle_status: "submitted" };

beforeEach(() => {
  vi.clearAllMocks();
});

describe("TaskDecisionModal", () => {
  it("renders nothing when the task has no pending decision", () => {
    const { container } = render(<TaskDecisionModal projectId="p1" task={{ ...workTask, lifecycle_status: "in_progress" }} onDecided={vi.fn()}/>);
    expect(container).toBeEmptyDOMElement();
  });

  it("offers Verify for a submitted work task and calls the verify endpoint", async () => {
    taskExecutionApi.verify.mockResolvedValue({});
    const onDecided = vi.fn();
    render(<TaskDecisionModal projectId="p1" task={workTask} onDecided={onDecided}/>);
    expect(screen.getByText("Supervisor verification")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Verify" }));
    fireEvent.click(screen.getByRole("button", { name: /confirm verify/i }));
    await waitFor(() => expect(taskExecutionApi.verify).toHaveBeenCalledWith("p1", "t1", { decision: "verified", remarks: null }));
    expect(onDecided).toHaveBeenCalledTimes(1);
  });

  it("requires a reason to reject and blocks submission until provided", async () => {
    taskExecutionApi.verify.mockResolvedValue({});
    render(<TaskDecisionModal projectId="p1" task={workTask} onDecided={vi.fn()}/>);
    fireEvent.click(screen.getByRole("button", { name: "Reject" }));
    fireEvent.submit(screen.getByRole("button", { name: /confirm rejection/i }).closest("form"));
    expect(await screen.findByText(/correction reason is required/i)).toBeInTheDocument();
    expect(taskExecutionApi.verify).not.toHaveBeenCalled();
    fireEvent.change(screen.getByLabelText(/correction reason/i), { target: { value: "Missing site photos." } });
    fireEvent.click(screen.getByRole("button", { name: /confirm rejection/i }));
    await waitFor(() => expect(taskExecutionApi.verify).toHaveBeenCalledWith("p1", "t1", { decision: "rejected", remarks: "Missing site photos." }));
  });

  it("offers Approve for Class A verified work and calls the approve endpoint", async () => {
    taskExecutionApi.approve.mockResolvedValue({});
    render(<TaskDecisionModal projectId="p1" task={classATask} onDecided={vi.fn()}/>);
    expect(screen.getByText("PM approval")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Approve" }));
    fireEvent.click(screen.getByRole("button", { name: /confirm approve/i }));
    await waitFor(() => expect(taskExecutionApi.approve).toHaveBeenCalledWith("p1", "t1", { decision: "approved", remarks: null }));
  });

  it("offers Approve directly for a submitted approval gate (no verification step)", async () => {
    taskExecutionApi.approve.mockResolvedValue({});
    render(<TaskDecisionModal projectId="p1" task={gateTask} onDecided={vi.fn()}/>);
    fireEvent.click(screen.getByRole("button", { name: "Approve" }));
    fireEvent.click(screen.getByRole("button", { name: /confirm approve/i }));
    await waitFor(() => expect(taskExecutionApi.approve).toHaveBeenCalledWith("p1", "t2", { decision: "approved", remarks: null }));
  });

  it("surfaces a backend error inline without closing the modal", async () => {
    taskExecutionApi.verify.mockRejectedValue(new Error("This task has no pending progress submission to verify."));
    render(<TaskDecisionModal projectId="p1" task={workTask} onDecided={vi.fn()}/>);
    fireEvent.click(screen.getByRole("button", { name: "Verify" }));
    fireEvent.click(screen.getByRole("button", { name: /confirm verify/i }));
    expect(await screen.findByText("This task has no pending progress submission to verify.")).toBeInTheDocument();
  });
});
