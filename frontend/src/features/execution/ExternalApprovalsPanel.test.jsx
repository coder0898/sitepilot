import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { projectsApi } from "../../api/projectsApi";
import { taskExecutionApi } from "../../api/taskExecutionApi";
import { ExternalApprovalsPanel } from "./components/ExternalApprovalsPanel";

vi.mock("../../api/taskExecutionApi", () => ({ taskExecutionApi: {
  listExternalApprovals: vi.fn(), decideExternalApproval: vi.fn(),
  assignExternalApproval: vi.fn(), reassignExternalApproval: vi.fn(), unassignExternalApproval: vi.fn(),
  submitExternalApprovalEvidence: vi.fn(),
  list: vi.fn(), detail: vi.fn(),
} }));
vi.mock("../../api/projectsApi", () => ({ projectsApi: { detail: vi.fn(), externalGates: vi.fn() } }));

const gate = (applicability_state = "pending_review") => ({ id: `g-${Math.random()}`, applicability_state });

const baseApproval = {
  id: "a1", project_id: "p1", project_gate_id: "g1", gate_code: "FIRE-NOC", gate_name: "Fire NOC",
  status: "unassigned", blocking: true, coverage_state: "exact", coverage_text: null,
  covered_task_ids: ["t1", "t2"],
  assigned_to_user_id: null, assigned_to_name: null, assigned_by: null, assigned_at: null,
  rejection_reason: null, decided_by: null, decided_by_name: null, decided_at: null,
};

const admin = { id: "u-adm", role: "admin" };
const pm = { id: "u-pm", role: "project_manager" };
const supervisor = { id: "u-sup", role: "supervisor" };
const employee = { id: "u-emp", role: "internal_employee" };
const otherEmployee = { id: "u-emp2", role: "internal_employee" };

const membership = (user, projectRole) => ({ id: `m-${user.id}`, user_id: user.id, employee_id: `emp-${user.id}`, name: user.id, project_role: projectRole, ends_at: null });
const projectWith = (...memberships) => ({ id: "p1", memberships });
const fullProject = projectWith(
  membership(pm, "project_manager"),
  membership(supervisor, "site_supervisor"),
  membership(employee, "internal_employee"),
  membership(otherEmployee, "internal_employee"),
);

const renderPanel = (user, props = {}) => render(
  <ExternalApprovalsPanel projectId="p1" project={fullProject} user={user} {...props}/>,
);

beforeEach(() => {
  vi.clearAllMocks();
  taskExecutionApi.listExternalApprovals.mockResolvedValue([baseApproval]);
  projectsApi.externalGates.mockResolvedValue({ items: [gate("applicable")] });
});

describe("ExternalApprovalsPanel", () => {
  it("reads the execution-layer approvals, not the planning-layer gates", async () => {
    renderPanel(admin);
    expect(await screen.findByText("Fire NOC")).toBeInTheDocument();
    expect(taskExecutionApi.listExternalApprovals).toHaveBeenCalledWith("p1");
  });

  // ---- assignment (Admin only) -------------------------------------------

  it("offers Admin an Assign action on an unassigned gate", async () => {
    renderPanel(admin);
    expect(await screen.findByRole("button", { name: "Assign" })).toBeInTheDocument();
  });

  it("does not offer PM or Supervisor an Assign action", async () => {
    renderPanel(pm);
    await screen.findByText("Fire NOC");
    expect(screen.queryByRole("button", { name: "Assign" })).not.toBeInTheDocument();
  });

  it("shows the employee picker's empty state when no eligible employees exist", async () => {
    renderPanel(admin, { project: projectWith(membership(pm, "project_manager")) });
    fireEvent.click(await screen.findByRole("button", { name: "Assign" }));
    expect(await screen.findByText("No eligible employees on this project")).toBeInTheDocument();
  });

  it("assigns the gate to the selected employee", async () => {
    taskExecutionApi.assignExternalApproval.mockResolvedValue({});
    renderPanel(admin);
    fireEvent.click(await screen.findByRole("button", { name: "Assign" }));
    fireEvent.change(await screen.findByRole("combobox"), { target: { value: employee.id } });
    fireEvent.click(screen.getAllByRole("button", { name: "Assign" })[1]);
    await waitFor(() => expect(taskExecutionApi.assignExternalApproval).toHaveBeenCalledWith(
      "p1", "a1", { assignee_user_id: employee.id },
    ));
  });

  it("surfaces an assignment failure inline without closing the modal", async () => {
    taskExecutionApi.assignExternalApproval.mockRejectedValue(new Error("This external approval is already assigned."));
    renderPanel(admin);
    fireEvent.click(await screen.findByRole("button", { name: "Assign" }));
    fireEvent.change(await screen.findByRole("combobox"), { target: { value: employee.id } });
    fireEvent.click(screen.getAllByRole("button", { name: "Assign" })[1]);
    expect(await screen.findByRole("alert")).toHaveTextContent(/already assigned/i);
  });

  it("offers Reassign and Unassign on an assigned gate, not Assign", async () => {
    taskExecutionApi.listExternalApprovals.mockResolvedValue([
      { ...baseApproval, status: "assigned", assigned_to_user_id: employee.id, assigned_to_name: "employee" },
    ]);
    renderPanel(admin);
    expect(await screen.findByRole("button", { name: "Reassign" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Unassign" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Assign" })).not.toBeInTheDocument();
  });

  it("unassigns an assigned gate", async () => {
    taskExecutionApi.listExternalApprovals.mockResolvedValue([
      { ...baseApproval, status: "assigned", assigned_to_user_id: employee.id, assigned_to_name: "employee" },
    ]);
    taskExecutionApi.unassignExternalApproval.mockResolvedValue({});
    renderPanel(admin);
    fireEvent.click(await screen.findByRole("button", { name: "Unassign" }));
    await waitFor(() => expect(taskExecutionApi.unassignExternalApproval).toHaveBeenCalledWith("p1", "a1"));
  });

  // ---- submission (assignee only) ----------------------------------------

  it("shows the assignee a submission form on their assigned gate", async () => {
    taskExecutionApi.listExternalApprovals.mockResolvedValue([
      { ...baseApproval, status: "assigned", assigned_to_user_id: employee.id, assigned_to_name: "employee" },
    ]);
    renderPanel(employee);
    expect(await screen.findByText("Submit evidence")).toBeInTheDocument();
  });

  it("does not show the submission form to a different employee on someone else's assigned gate", async () => {
    taskExecutionApi.listExternalApprovals.mockResolvedValue([
      { ...baseApproval, status: "assigned", assigned_to_user_id: employee.id, assigned_to_name: "employee" },
    ]);
    renderPanel(otherEmployee);
    await screen.findByText("Fire NOC");
    expect(screen.queryByText("Submit evidence")).not.toBeInTheDocument();
  });

  it("submits a note and evidence for the assignee's gate", async () => {
    taskExecutionApi.listExternalApprovals.mockResolvedValue([
      { ...baseApproval, status: "assigned", assigned_to_user_id: employee.id, assigned_to_name: "employee" },
    ]);
    taskExecutionApi.submitExternalApprovalEvidence.mockResolvedValue({});
    renderPanel(employee);
    fireEvent.change(await screen.findByPlaceholderText(/describe what's attached/i), { target: { value: "NOC attached." } });
    fireEvent.click(screen.getByRole("button", { name: "Submit for review" }));
    await waitFor(() => expect(taskExecutionApi.submitExternalApprovalEvidence).toHaveBeenCalledWith("p1", "a1", expect.any(FormData)));
  });

  it("displays the rejection reason above the resubmission form", async () => {
    taskExecutionApi.listExternalApprovals.mockResolvedValue([
      { ...baseApproval, status: "assigned", assigned_to_user_id: employee.id, assigned_to_name: "employee", rejection_reason: "Missing a signature page." },
    ]);
    renderPanel(employee);
    expect(await screen.findByText(/Missing a signature page\./)).toBeInTheDocument();
  });

  // ---- decision (Admin only) ----------------------------------------------

  it("offers Approve and Reject to Admin on a submitted gate", async () => {
    taskExecutionApi.listExternalApprovals.mockResolvedValue([
      { ...baseApproval, status: "submitted", assigned_to_user_id: employee.id, assigned_to_name: "employee" },
    ]);
    renderPanel(admin);
    expect(await screen.findByRole("button", { name: "Approve" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Reject" })).toBeInTheDocument();
  });

  it("does not offer PM a decision action, unlike the old PM-fallback rule", async () => {
    taskExecutionApi.listExternalApprovals.mockResolvedValue([
      { ...baseApproval, status: "submitted", assigned_to_user_id: employee.id, assigned_to_name: "employee" },
    ]);
    renderPanel(pm);
    await screen.findByText("Fire NOC");
    expect(screen.queryByRole("button", { name: "Approve" })).not.toBeInTheDocument();
  });

  it("cannot submit a rejection without a reason", async () => {
    taskExecutionApi.listExternalApprovals.mockResolvedValue([
      { ...baseApproval, status: "submitted", assigned_to_user_id: employee.id, assigned_to_name: "employee" },
    ]);
    renderPanel(admin);
    fireEvent.click(await screen.findByRole("button", { name: "Reject" }));
    const confirm = await screen.findByRole("button", { name: "Confirm rejection" });
    expect(confirm).toBeDisabled();
    fireEvent.change(screen.getByPlaceholderText(/explain why this approval is being refused/i), { target: { value: "  " } });
    expect(confirm).toBeDisabled();
    expect(taskExecutionApi.decideExternalApproval).not.toHaveBeenCalled();
  });

  it("records a rejection once a reason is given", async () => {
    taskExecutionApi.listExternalApprovals.mockResolvedValue([
      { ...baseApproval, status: "submitted", assigned_to_user_id: employee.id, assigned_to_name: "employee" },
    ]);
    taskExecutionApi.decideExternalApproval.mockResolvedValue({});
    renderPanel(admin);
    fireEvent.click(await screen.findByRole("button", { name: "Reject" }));
    fireEvent.change(await screen.findByPlaceholderText(/explain why this approval is being refused/i), { target: { value: "Drawings rejected by the authority." } });
    fireEvent.click(screen.getByRole("button", { name: "Confirm rejection" }));
    await waitFor(() => expect(taskExecutionApi.decideExternalApproval).toHaveBeenCalledWith(
      "p1", "a1", { decision: "rejected", reason: "Drawings rejected by the authority." },
    ));
  });

  it("records an approval without requiring remarks", async () => {
    taskExecutionApi.listExternalApprovals.mockResolvedValue([
      { ...baseApproval, status: "submitted", assigned_to_user_id: employee.id, assigned_to_name: "employee" },
    ]);
    taskExecutionApi.decideExternalApproval.mockResolvedValue({});
    renderPanel(admin);
    fireEvent.click(await screen.findByRole("button", { name: "Approve" }));
    const confirm = await screen.findByRole("button", { name: "Confirm approval" });
    expect(confirm).toBeEnabled();
    fireEvent.click(confirm);
    await waitFor(() => expect(taskExecutionApi.decideExternalApproval).toHaveBeenCalledWith(
      "p1", "a1", { decision: "approved", reason: null },
    ));
  });

  it("refetches so the decided approval shows its new status", async () => {
    taskExecutionApi.listExternalApprovals.mockResolvedValue([
      { ...baseApproval, status: "submitted", assigned_to_user_id: employee.id, assigned_to_name: "employee" },
    ]);
    taskExecutionApi.decideExternalApproval.mockResolvedValue({});
    renderPanel(admin);
    fireEvent.click(await screen.findByRole("button", { name: "Approve" }));
    fireEvent.click(await screen.findByRole("button", { name: "Confirm approval" }));
    await waitFor(() => expect(taskExecutionApi.listExternalApprovals).toHaveBeenCalledTimes(2));
  });

  // ---- read-only view (PM/Supervisor) --------------------------------------

  it("shows a Supervisor the approval but no action buttons regardless of status", async () => {
    taskExecutionApi.listExternalApprovals.mockResolvedValue([
      { ...baseApproval, status: "submitted", assigned_to_user_id: employee.id, assigned_to_name: "employee" },
    ]);
    renderPanel(supervisor);
    expect(await screen.findByText("Fire NOC")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Approve" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Assign" })).not.toBeInTheDocument();
    expect(screen.getByText(/only an Admin can assign or decide/i)).toBeInTheDocument();
  });

  it("offers no actions on an approval that is already approved", async () => {
    taskExecutionApi.listExternalApprovals.mockResolvedValue([
      { ...baseApproval, status: "approved", decided_by_name: "Priya", decided_at: "2026-08-10T09:00:00Z" },
    ]);
    renderPanel(admin);
    expect(await screen.findByText("Fire NOC")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Approve" })).not.toBeInTheDocument();
    expect(screen.getByText(/by Priya/)).toBeInTheDocument();
  });

  // R10: an unresolved approval links no tasks, so it can never surface as a
  // task's readiness reason. This panel is the only place it is visible.
  it("labels an approval whose coverage could not be resolved, and shows the prose", async () => {
    taskExecutionApi.listExternalApprovals.mockResolvedValue([
      { ...baseApproval, coverage_state: "unresolved", coverage_text: "All electrical works", covered_task_ids: [] },
    ]);
    renderPanel(admin);
    expect(await screen.findByText("Coverage unresolved")).toBeInTheDocument();
    expect(screen.getByText(/All electrical works/)).toBeInTheDocument();
  });

  it("surfaces a failed load rather than rendering an empty list as if there were none", async () => {
    taskExecutionApi.listExternalApprovals.mockRejectedValue(new Error("Server unavailable"));
    renderPanel(admin);
    expect(await screen.findByText("Server unavailable")).toBeInTheDocument();
  });

  it("reports a project whose gates were all ruled out as genuinely having none", async () => {
    taskExecutionApi.listExternalApprovals.mockResolvedValue([]);
    projectsApi.externalGates.mockResolvedValue({ items: [gate("not_applicable"), gate("not_applicable")] });
    renderPanel(admin);
    expect(await screen.findByText(/No external approvals apply to this project/i)).toBeInTheDocument();
  });

  describe("gates still awaiting an applicability decision", () => {
    beforeEach(() => {
      taskExecutionApi.listExternalApprovals.mockResolvedValue([]);
      projectsApi.externalGates.mockResolvedValue({ items: Array.from({ length: 32 }, () => gate()) });
    });

    it("says how many are awaiting review and what unblocks them", async () => {
      renderPanel(admin);
      expect(await screen.findByText(/32 external approvals are awaiting applicability review/i)).toBeInTheDocument();
      expect(screen.getByText(/decides, in this project's setup/i)).toBeInTheDocument();
    });
  });

  // This read only enriches an explanation, so losing it must never cost the
  // user the approvals they can actually act on.
  it("still renders the approvals when the planning-gate read fails", async () => {
    projectsApi.externalGates.mockRejectedValue(new Error("gates unavailable"));
    renderPanel(admin);
    expect(await screen.findByText("Fire NOC")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Assign" })).toBeInTheDocument();
    expect(screen.queryByText(/awaiting applicability review/i)).not.toBeInTheDocument();
  });
});
