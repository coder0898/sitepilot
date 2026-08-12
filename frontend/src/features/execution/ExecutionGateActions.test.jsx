import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { taskExecutionApi } from "../../api/taskExecutionApi";
import { ExecutionGateStatusControl, canRecordGateOutcome } from "./components/ExecutionGateActions";

vi.mock("../../api/taskExecutionApi", () => ({ taskExecutionApi: { recordGateStatus: vi.fn() } }));

const PM_ID = "pm-1";
const gate = { id: "g1", original_code: "E001", status: "pending_review", accountable_pm_user_id: PM_ID };
const accountablePm = { id: PM_ID, role: "project_manager" };
const otherPm = { id: "pm-2", role: "project_manager" };
const admin = { id: "a1", role: "admin" };
const superAdmin = { id: "sa1", role: "super_admin" };
const supervisor = { id: "s1", role: "supervisor" };

beforeEach(() => { vi.clearAllMocks(); });

describe("canRecordGateOutcome", () => {
  it("lets the accountable PM submit, approve, reject and resubmit", () => {
    expect(canRecordGateOutcome(accountablePm, gate, "pending_review", "submitted")).toBe(true);
    expect(canRecordGateOutcome(accountablePm, gate, "submitted", "approved")).toBe(true);
    expect(canRecordGateOutcome(accountablePm, gate, "submitted", "rejected")).toBe(true);
    expect(canRecordGateOutcome(accountablePm, gate, "rejected", "submitted")).toBe(true);
  });

  it("keeps not_required away from the accountable PM in both directions", () => {
    // Mirrors GATE_ADMIN_ONLY_TRANSITIONS. Reaching not_required stops the
    // gate blocking, which releases every task it holds - a readiness
    // bypass wearing the name of paperwork.
    expect(canRecordGateOutcome(accountablePm, gate, "pending_review", "not_required")).toBe(false);
    expect(canRecordGateOutcome(accountablePm, gate, "not_required", "pending_review")).toBe(false);
  });

  it("admits Admin and Super Admin to every transition", () => {
    for (const user of [admin, superAdmin]) {
      expect(canRecordGateOutcome(user, gate, "pending_review", "not_required")).toBe(true);
      expect(canRecordGateOutcome(user, gate, "submitted", "approved")).toBe(true);
    }
  });

  it("refuses a PM who is not this gate's accountable PM, and a Supervisor", () => {
    expect(canRecordGateOutcome(otherPm, gate, "submitted", "approved")).toBe(false);
    expect(canRecordGateOutcome(supervisor, gate, "submitted", "approved")).toBe(false);
  });
});

describe("ExecutionGateStatusControl", () => {
  it("offers no not_required option to a PM", () => {
    render(<ExecutionGateStatusControl projectId="p1" gate={gate} user={accountablePm} onRecorded={vi.fn()}/>);
    expect(screen.getByRole("option", { name: "Mark submitted" })).toBeInTheDocument();
    expect(screen.queryByRole("option", { name: "Mark not required" })).toBeNull();
  });

  it("offers it to an Admin", () => {
    render(<ExecutionGateStatusControl projectId="p1" gate={gate} user={admin} onRecorded={vi.fn()}/>);
    expect(screen.getByRole("option", { name: "Mark not required" })).toBeInTheDocument();
  });

  it("renders nothing for an actor with no permitted transition", () => {
    const { container } = render(<ExecutionGateStatusControl projectId="p1" gate={gate} user={supervisor} onRecorded={vi.fn()}/>);
    expect(container).toBeEmptyDOMElement();
  });

  it("records an outcome with its reason and refreshes", async () => {
    taskExecutionApi.recordGateStatus.mockResolvedValue({});
    const onRecorded = vi.fn().mockResolvedValue();
    render(<ExecutionGateStatusControl projectId="p1" gate={{ ...gate, status: "submitted" }} user={accountablePm} onRecorded={onRecorded}/>);

    fireEvent.change(screen.getByLabelText("Record outcome"), { target: { value: "approved" } });
    fireEvent.change(screen.getByLabelText("Reason"), { target: { value: "Landlord signed on site." } });
    fireEvent.click(screen.getByRole("button", { name: /record/i }));

    await waitFor(() => expect(taskExecutionApi.recordGateStatus).toHaveBeenCalledWith(
      "p1", "g1", { status: "approved", reason: "Landlord signed on site." },
    ));
    await waitFor(() => expect(onRecorded).toHaveBeenCalled());
  });

  it("surfaces the server's message when it refuses", async () => {
    taskExecutionApi.recordGateStatus.mockRejectedValue(new Error("Only Admin can mark an approval not required."));
    render(<ExecutionGateStatusControl projectId="p1" gate={{ ...gate, status: "submitted" }} user={accountablePm} onRecorded={vi.fn()}/>);
    fireEvent.change(screen.getByLabelText("Record outcome"), { target: { value: "approved" } });
    fireEvent.change(screen.getByLabelText("Reason"), { target: { value: "Signed." } });
    fireEvent.click(screen.getByRole("button", { name: /record/i }));
    expect(await screen.findByText("Only Admin can mark an approval not required.")).toBeInTheDocument();
  });

  it("cannot be submitted without a reason", () => {
    render(<ExecutionGateStatusControl projectId="p1" gate={{ ...gate, status: "submitted" }} user={accountablePm} onRecorded={vi.fn()}/>);
    fireEvent.change(screen.getByLabelText("Record outcome"), { target: { value: "approved" } });
    expect(screen.getByRole("button", { name: /record/i })).toBeDisabled();
  });
});
