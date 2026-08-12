import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { taskExecutionApi } from "../../api/taskExecutionApi";
import { ExecutionGateStatusControl, canRecordGateOutcome } from "./components/ExecutionGateActions";

vi.mock("../../api/taskExecutionApi", () => ({ taskExecutionApi: { recordGateStatus: vi.fn() } }));

const PM_ID = "pm-1";
const DELEGATE_ID = "emp-1";
const gate = { id: "g1", original_code: "E001", status: "pending_review", accountable_pm_user_id: PM_ID, active_delegate_user_ids: [] };
const delegatedGate = { ...gate, active_delegate_user_ids: [DELEGATE_ID] };
const accountablePm = { id: PM_ID, role: "project_manager" };
const otherPm = { id: "pm-2", role: "project_manager" };
const admin = { id: "a1", role: "admin" };
const superAdmin = { id: "sa1", role: "super_admin" };
const supervisor = { id: "s1", role: "supervisor" };
const delegate = { id: DELEGATE_ID, role: "internal_employee" };

beforeEach(() => { vi.clearAllMocks(); });

describe("canRecordGateOutcome", () => {
  it("lets a delegate record submission and resubmission", () => {
    expect(canRecordGateOutcome(delegate, delegatedGate, "pending_review", "submitted")).toBe(true);
    expect(canRecordGateOutcome(delegate, delegatedGate, "rejected", "submitted")).toBe(true);
  });

  it("keeps approval and rejection away from the delegate", () => {
    // "I lodged it" is theirs to state; "the landlord approved" is not.
    expect(canRecordGateOutcome(delegate, delegatedGate, "submitted", "approved")).toBe(false);
    expect(canRecordGateOutcome(delegate, delegatedGate, "submitted", "rejected")).toBe(false);
    expect(canRecordGateOutcome(delegate, delegatedGate, "approved", "submitted")).toBe(false);
    expect(canRecordGateOutcome(delegate, delegatedGate, "pending_review", "not_required")).toBe(false);
  });

  it("admits Admin and Super Admin to every transition", () => {
    for (const user of [admin, superAdmin]) {
      expect(canRecordGateOutcome(user, gate, "pending_review", "not_required")).toBe(true);
      expect(canRecordGateOutcome(user, gate, "submitted", "approved")).toBe(true);
    }
  });

  it("refuses every Project Manager, including this gate's accountable one", () => {
    // External approvals are Admin's responsibility. The accountable PM is
    // named on the gate for escalation, not for permission.
    for (const from_to of [["pending_review", "submitted"], ["submitted", "approved"]]) {
      expect(canRecordGateOutcome(accountablePm, gate, ...from_to)).toBe(false);
      expect(canRecordGateOutcome(otherPm, gate, ...from_to)).toBe(false);
    }
  });

  it("refuses a Supervisor, and an Internal Employee who is not delegated", () => {
    expect(canRecordGateOutcome(supervisor, gate, "pending_review", "submitted")).toBe(false);
    expect(canRecordGateOutcome(delegate, gate, "pending_review", "submitted")).toBe(false);
  });
});

describe("ExecutionGateStatusControl", () => {
  it("offers a delegate only the submit option", () => {
    render(<ExecutionGateStatusControl projectId="p1" gate={delegatedGate} user={delegate} onRecorded={vi.fn()}/>);
    expect(screen.getByRole("option", { name: "Mark submitted" })).toBeInTheDocument();
    expect(screen.queryByRole("option", { name: "Mark not required" })).toBeNull();
  });

  it("offers it to an Admin", () => {
    render(<ExecutionGateStatusControl projectId="p1" gate={gate} user={admin} onRecorded={vi.fn()}/>);
    expect(screen.getByRole("option", { name: "Mark not required" })).toBeInTheDocument();
  });

  it("renders nothing for a Supervisor, a PM, or an undelegated employee", () => {
    // `gate` has no active delegates, so the employee is undelegated here.
    for (const user of [supervisor, accountablePm, otherPm, delegate]) {
      const { container } = render(<ExecutionGateStatusControl projectId="p1" gate={gate} user={user} onRecorded={vi.fn()}/>);
      expect(container).toBeEmptyDOMElement();
    }
  });

  it("records an outcome with its reason and refreshes", async () => {
    taskExecutionApi.recordGateStatus.mockResolvedValue({});
    const onRecorded = vi.fn().mockResolvedValue();
    render(<ExecutionGateStatusControl projectId="p1" gate={{ ...gate, status: "submitted" }} user={admin} onRecorded={onRecorded}/>);

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
    render(<ExecutionGateStatusControl projectId="p1" gate={{ ...gate, status: "submitted" }} user={admin} onRecorded={vi.fn()}/>);
    fireEvent.change(screen.getByLabelText("Record outcome"), { target: { value: "approved" } });
    fireEvent.change(screen.getByLabelText("Reason"), { target: { value: "Signed." } });
    fireEvent.click(screen.getByRole("button", { name: /record/i }));
    expect(await screen.findByText("Only Admin can mark an approval not required.")).toBeInTheDocument();
  });

  it("cannot be submitted without a reason", () => {
    render(<ExecutionGateStatusControl projectId="p1" gate={{ ...gate, status: "submitted" }} user={admin} onRecorded={vi.fn()}/>);
    fireEvent.change(screen.getByLabelText("Record outcome"), { target: { value: "approved" } });
    expect(screen.getByRole("button", { name: /record/i })).toBeDisabled();
  });
});
