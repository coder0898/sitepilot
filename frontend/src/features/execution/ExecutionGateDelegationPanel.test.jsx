import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { taskExecutionApi } from "../../api/taskExecutionApi";
import { ExecutionGateDelegationPanel, canDelegateGate } from "./components/ExecutionGateDelegationPanel";

vi.mock("../../api/taskExecutionApi", () => ({ taskExecutionApi: {
  gateDelegations: vi.fn(), delegateGate: vi.fn(), endGateDelegation: vi.fn(),
} }));

const gate = { id: "g1", original_code: "E001", status: "pending_review", active_delegate_user_ids: [] };
const admin = { id: "a1", role: "admin" };
const superAdmin = { id: "sa1", role: "super_admin" };
const pm = { id: "pm-1", role: "project_manager" };
const supervisor = { id: "s1", role: "supervisor" };

const employees = [
  { employee_id: "emp-1", user_id: "u1", name: "Asha Rao", project_role: "internal_employee" },
  { employee_id: "emp-2", user_id: "u2", name: "Vikram Shah", project_role: "internal_employee" },
];

function delegation(overrides = {}) {
  return {
    id: "d1", execution_gate_id: "g1", employee_id: "emp-1",
    instruction: "Chase the landlord's agent for the signed letter.",
    status: "active", ends_at: null, end_reason: null, ...overrides,
  };
}

function renderPanel(user = admin, props = {}) {
  return render(<ExecutionGateDelegationPanel
    projectId="p1" gate={gate} user={user} internalEmployees={employees}
    onChanged={vi.fn().mockResolvedValue()} {...props}/>);
}

beforeEach(() => {
  vi.clearAllMocks();
  taskExecutionApi.gateDelegations.mockResolvedValue([]);
});

describe("canDelegateGate", () => {
  it("is Admin and Super Admin only", () => {
    expect(canDelegateGate(admin)).toBe(true);
    expect(canDelegateGate(superAdmin)).toBe(true);
    expect(canDelegateGate(pm)).toBe(false);
    expect(canDelegateGate(supervisor)).toBe(false);
  });
});

describe("ExecutionGateDelegationPanel", () => {
  it("offers the Delegate control to an Admin", async () => {
    renderPanel(admin);
    expect(await screen.findByRole("button", { name: /delegate/i })).toBeInTheDocument();
  });

  it("does not offer it to a PM or a Supervisor, but still shows them who is chasing", async () => {
    taskExecutionApi.gateDelegations.mockResolvedValue([delegation()]);
    for (const user of [pm, supervisor]) {
      const { unmount } = renderPanel(user);
      expect(await screen.findByText("Asha Rao")).toBeInTheDocument();
      expect(screen.queryByRole("button", { name: /^delegate$/i })).toBeNull();
      unmount();
    }
  });

  it("tells a non-Admin why the list is empty", async () => {
    renderPanel(pm);
    expect(await screen.findByText(/Only an Admin can delegate it/)).toBeInTheDocument();
  });

  it("delegates with an employee and an instruction, then refreshes the gate list", async () => {
    taskExecutionApi.delegateGate.mockResolvedValue({});
    const onChanged = vi.fn().mockResolvedValue();
    renderPanel(admin, { onChanged });

    fireEvent.click(await screen.findByRole("button", { name: /delegate/i }));
    fireEvent.change(screen.getByLabelText("Internal Employee"), { target: { value: "emp-2" } });
    fireEvent.change(screen.getByLabelText("What are they chasing?"), {
      target: { value: "Get the fire NOC lodged this week." },
    });
    fireEvent.click(screen.getByRole("button", { name: /^delegate$/i }));

    await waitFor(() => expect(taskExecutionApi.delegateGate).toHaveBeenCalledWith(
      "p1", "g1", { employee_id: "emp-2", instruction: "Get the fire NOC lodged this week." },
    ));
    // The gate list carries active_delegate_user_ids, which decides whether
    // the delegate is offered the submit control.
    await waitFor(() => expect(onChanged).toHaveBeenCalled());
  });

  it("cannot be submitted without both an employee and an instruction", async () => {
    renderPanel(admin);
    fireEvent.click(await screen.findByRole("button", { name: /delegate/i }));
    const submit = screen.getByRole("button", { name: /^delegate$/i });
    expect(submit).toBeDisabled();

    fireEvent.change(screen.getByLabelText("Internal Employee"), { target: { value: "emp-1" } });
    expect(submit).toBeDisabled();

    fireEvent.change(screen.getByLabelText("What are they chasing?"), { target: { value: "Chase it." } });
    expect(submit).toBeEnabled();
  });

  it("does not offer an employee who is already chasing this approval", async () => {
    taskExecutionApi.gateDelegations.mockResolvedValue([delegation({ employee_id: "emp-1" })]);
    renderPanel(admin);
    fireEvent.click(await screen.findByRole("button", { name: /delegate/i }));
    expect(screen.getByRole("option", { name: "Vikram Shah" })).toBeInTheDocument();
    expect(screen.queryByRole("option", { name: "Asha Rao" })).toBeNull();
  });

  it("says so when everyone on the project is already chasing it", async () => {
    taskExecutionApi.gateDelegations.mockResolvedValue([
      delegation({ id: "d1", employee_id: "emp-1" }),
      delegation({ id: "d2", employee_id: "emp-2" }),
    ]);
    renderPanel(admin);
    expect(await screen.findByText(/Every Internal Employee on this project is already chasing it/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /delegate/i })).toBeDisabled();
  });

  it("surfaces the server's message when it refuses", async () => {
    taskExecutionApi.delegateGate.mockRejectedValue(new Error("Only Admin can delegate an external approval."));
    renderPanel(admin);
    fireEvent.click(await screen.findByRole("button", { name: /delegate/i }));
    fireEvent.change(screen.getByLabelText("Internal Employee"), { target: { value: "emp-1" } });
    fireEvent.change(screen.getByLabelText("What are they chasing?"), { target: { value: "Chase it." } });
    fireEvent.click(screen.getByRole("button", { name: /^delegate$/i }));
    expect(await screen.findByText("Only Admin can delegate an external approval.")).toBeInTheDocument();
  });

  it("ends a delegation with a reason", async () => {
    taskExecutionApi.gateDelegations.mockResolvedValue([delegation()]);
    taskExecutionApi.endGateDelegation.mockResolvedValue({});
    vi.spyOn(window, "prompt").mockReturnValue("Handed to the site team.");
    renderPanel(admin);

    fireEvent.click(await screen.findByRole("button", { name: /^end$/i }));
    await waitFor(() => expect(taskExecutionApi.endGateDelegation).toHaveBeenCalledWith(
      "p1", "g1", "d1", { reason: "Handed to the site team." },
    ));
  });

  it("does not end a delegation when the reason prompt is cancelled", async () => {
    taskExecutionApi.gateDelegations.mockResolvedValue([delegation()]);
    vi.spyOn(window, "prompt").mockReturnValue(null);
    renderPanel(admin);

    fireEvent.click(await screen.findByRole("button", { name: /^end$/i }));
    expect(taskExecutionApi.endGateDelegation).not.toHaveBeenCalled();
  });

  it("keeps an ended delegation on the record with its reason", async () => {
    taskExecutionApi.gateDelegations.mockResolvedValue([
      delegation({ status: "ended", ends_at: "2026-08-12T10:00:00Z", end_reason: "Reassigned." }),
    ]);
    renderPanel(admin);
    expect(await screen.findByText("Ended")).toBeInTheDocument();
    expect(screen.getByText(/Ended: Reassigned\./)).toBeInTheDocument();
    // An ended delegation offers no End control.
    expect(screen.queryByRole("button", { name: /^end$/i })).toBeNull();
  });

  it("surfaces a failed load without blowing up the panel", async () => {
    taskExecutionApi.gateDelegations.mockRejectedValue(new Error("Nope."));
    renderPanel(admin);
    expect(await screen.findByText("Nope.")).toBeInTheDocument();
  });
});
