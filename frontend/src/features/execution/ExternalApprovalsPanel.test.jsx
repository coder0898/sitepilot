import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { projectsApi } from "../../api/projectsApi";
import { taskExecutionApi } from "../../api/taskExecutionApi";
import { ExternalApprovalsPanel } from "./components/ExternalApprovalsPanel";

vi.mock("../../api/taskExecutionApi", () => ({ taskExecutionApi: {
  listExternalApprovals: vi.fn(), decideExternalApproval: vi.fn(),
  assignExternalApproval: vi.fn(), reassignExternalApproval: vi.fn(), unassignExternalApproval: vi.fn(),
  submitExternalApprovalEvidence: vi.fn(), downloadExternalApprovalEvidence: vi.fn(),
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
  submissions: [],
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

// Selects a row by its approval code, opening the right-side review panel -
// every mutating action (Assign aside, which the table also exposes inline)
// now lives in that panel, not the row itself.
async function openApproval(code) {
  fireEvent.click(await screen.findByText(code));
}

beforeEach(() => {
  vi.clearAllMocks();
  taskExecutionApi.listExternalApprovals.mockResolvedValue([baseApproval]);
  taskExecutionApi.list.mockResolvedValue([]);
  projectsApi.externalGates.mockResolvedValue({ items: [gate("applicable")] });
});

describe("ExternalApprovalsPanel", () => {
  it("reads the execution-layer approvals, not the planning-layer gates", async () => {
    renderPanel(admin);
    expect(await screen.findByText("Fire NOC")).toBeInTheDocument();
    expect(taskExecutionApi.listExternalApprovals).toHaveBeenCalledWith("p1");
  });

  it("keeps the Admin-only, employee-only workflow: no PM or Supervisor label anywhere", async () => {
    renderPanel(admin);
    await screen.findByText("Fire NOC");
    expect(screen.queryByText(/\bPM\b/)).not.toBeInTheDocument();
    expect(screen.queryByText(/project manager/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/supervisor/i)).not.toBeInTheDocument();
  });

  it("shows the workflow strip's four steps without mentioning PM or Supervisor", async () => {
    renderPanel(admin);
    expect(await screen.findByText("Admin Assigns")).toBeInTheDocument();
    expect(screen.getByText("Employee Updates")).toBeInTheDocument();
    expect(screen.getByText("Submitted to Admin")).toBeInTheDocument();
    expect(screen.getByText("Admin Review")).toBeInTheDocument();
  });

  it("does not render the approval detail drawer until a row is selected, then opens it", async () => {
    renderPanel(admin);
    await screen.findByText(baseApproval.gate_code);
    expect(screen.queryByText("Assignment summary")).not.toBeInTheDocument();
    await openApproval(baseApproval.gate_code);
    expect(await screen.findByText("Assignment summary")).toBeInTheDocument();
  });

  // ---- KPI cards -----------------------------------------------------------

  it("counts approvals into the KPI cards from the same array it renders", async () => {
    taskExecutionApi.listExternalApprovals.mockResolvedValue([
      { ...baseApproval, id: "a1", status: "unassigned", blocking: false },
      { ...baseApproval, id: "a2", status: "submitted", blocking: false, assigned_to_user_id: employee.id, assigned_to_name: "employee" },
    ]);
    renderPanel(admin);
    const group = await screen.findByRole("group", { name: /external approvals summary/i });
    const totalCard = within(group).getByText("Total Approvals").closest("article");
    expect(within(totalCard).getByText("2")).toBeInTheDocument();
    const submittedCard = within(group).getByText("Submitted for Review").closest("article");
    expect(within(submittedCard).getByText("1")).toBeInTheDocument();
  });

  // ---- search / filter -------------------------------------------------

  it("narrows the table by search", async () => {
    taskExecutionApi.listExternalApprovals.mockResolvedValue([
      { ...baseApproval, id: "a1", gate_code: "FIRE-NOC", gate_name: "Fire NOC" },
      { ...baseApproval, id: "a2", gate_code: "ENV-001", gate_name: "Environmental Clearance" },
    ]);
    renderPanel(admin);
    await screen.findByText("Fire NOC");
    fireEvent.change(screen.getByPlaceholderText(/search by approval code or title/i), { target: { value: "environmental" } });
    await waitFor(() => expect(screen.queryByText("Fire NOC")).not.toBeInTheDocument());
    expect(screen.getByText("Environmental Clearance")).toBeInTheDocument();
  });

  it("narrows the table by the status filter", async () => {
    taskExecutionApi.listExternalApprovals.mockResolvedValue([
      { ...baseApproval, id: "a1", gate_code: "FIRE-NOC", gate_name: "Fire NOC", status: "unassigned" },
      { ...baseApproval, id: "a2", gate_code: "ENV-001", gate_name: "Environmental Clearance", status: "approved", decided_by_name: "Admin", decided_at: "2026-08-10T00:00:00Z" },
    ]);
    renderPanel(admin);
    await screen.findByText("Fire NOC");
    fireEvent.change(screen.getByLabelText(/filter by status/i), { target: { value: "approved" } });
    await waitFor(() => expect(screen.queryByText("Fire NOC")).not.toBeInTheDocument());
    expect(screen.getByText("Environmental Clearance")).toBeInTheDocument();
  });

  // ---- assignment (Admin only) -------------------------------------------

  it("offers Admin an Assign action on an unassigned approval", async () => {
    renderPanel(admin);
    expect(await screen.findByRole("button", { name: "Assign" })).toBeInTheDocument();
  });

  it("does not offer PM or Supervisor an Assign action, only View", async () => {
    renderPanel(pm);
    await screen.findByText("Fire NOC");
    expect(screen.queryByRole("button", { name: "Assign" })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "View" })).toBeInTheDocument();
  });

  it("shows the employee picker's empty state when no eligible internal employees exist", async () => {
    renderPanel(admin, { project: projectWith(membership(pm, "project_manager")) });
    fireEvent.click(await screen.findByRole("button", { name: "Assign" }));
    expect(await screen.findByText("No eligible employees on this project")).toBeInTheDocument();
  });

  it("assigns the approval to the selected internal employee", async () => {
    taskExecutionApi.assignExternalApproval.mockResolvedValue({});
    renderPanel(admin);
    fireEvent.click(await screen.findByRole("button", { name: "Assign" }));
    const dialog = await screen.findByRole("dialog");
    fireEvent.change(within(dialog).getByRole("combobox"), { target: { value: employee.id } });
    fireEvent.click(within(dialog).getByRole("button", { name: "Assign" }));
    await waitFor(() => expect(taskExecutionApi.assignExternalApproval).toHaveBeenCalledWith(
      "p1", "a1", { assignee_user_id: employee.id },
    ));
  });

  it("surfaces an assignment failure inline without closing the modal", async () => {
    taskExecutionApi.assignExternalApproval.mockRejectedValue(new Error("This external approval is already assigned."));
    renderPanel(admin);
    fireEvent.click(await screen.findByRole("button", { name: "Assign" }));
    const dialog = await screen.findByRole("dialog");
    fireEvent.change(within(dialog).getByRole("combobox"), { target: { value: employee.id } });
    fireEvent.click(within(dialog).getByRole("button", { name: "Assign" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(/already assigned/i);
  });

  it("offers Reassign and Unassign inside the panel of an assigned approval, not Assign", async () => {
    taskExecutionApi.listExternalApprovals.mockResolvedValue([
      { ...baseApproval, status: "assigned", assigned_to_user_id: employee.id, assigned_to_name: "employee" },
    ]);
    renderPanel(admin);
    await openApproval("FIRE-NOC");
    expect(await screen.findByRole("button", { name: /reassign/i })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Unassign" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Assign" })).not.toBeInTheDocument();
  });

  it("unassigns an assigned approval", async () => {
    taskExecutionApi.listExternalApprovals.mockResolvedValue([
      { ...baseApproval, status: "assigned", assigned_to_user_id: employee.id, assigned_to_name: "employee" },
    ]);
    taskExecutionApi.unassignExternalApproval.mockResolvedValue({});
    renderPanel(admin);
    await openApproval("FIRE-NOC");
    fireEvent.click(await screen.findByRole("button", { name: "Unassign" }));
    await waitFor(() => expect(taskExecutionApi.unassignExternalApproval).toHaveBeenCalledWith("p1", "a1"));
  });

  // ---- submission (assignee only) ----------------------------------------

  it("shows the assignee an update/submit form on their own assigned approval", async () => {
    taskExecutionApi.listExternalApprovals.mockResolvedValue([
      { ...baseApproval, status: "assigned", assigned_to_user_id: employee.id, assigned_to_name: "employee" },
    ]);
    renderPanel(employee);
    await openApproval("FIRE-NOC");
    expect(await screen.findByText("Update / submit evidence")).toBeInTheDocument();
  });

  it("does not show the update form, or any admin action, to a different employee on someone else's approval", async () => {
    taskExecutionApi.listExternalApprovals.mockResolvedValue([
      { ...baseApproval, status: "assigned", assigned_to_user_id: employee.id, assigned_to_name: "employee" },
    ]);
    renderPanel(otherEmployee);
    // Backend already scopes an internal_employee actor to their own
    // assigned approvals (list_for_project), so otherEmployee would see none
    // in real use; this only exercises the panel's own role gate directly.
    await screen.findByText("Fire NOC");
    await openApproval("FIRE-NOC");
    expect(screen.queryByText("Update / submit evidence")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Approve" })).not.toBeInTheDocument();
  });

  it("submits a note and evidence for the assignee's own approval", async () => {
    taskExecutionApi.listExternalApprovals.mockResolvedValue([
      { ...baseApproval, status: "assigned", assigned_to_user_id: employee.id, assigned_to_name: "employee" },
    ]);
    taskExecutionApi.submitExternalApprovalEvidence.mockResolvedValue({});
    renderPanel(employee);
    await openApproval("FIRE-NOC");
    fireEvent.change(await screen.findByPlaceholderText(/describe what's attached/i), { target: { value: "NOC attached." } });
    fireEvent.click(screen.getByRole("button", { name: "Submit for Admin review" }));
    await waitFor(() => expect(taskExecutionApi.submitExternalApprovalEvidence).toHaveBeenCalledWith("p1", "a1", expect.any(FormData)));
  });

  it("displays the rejection reason above the resubmission form", async () => {
    taskExecutionApi.listExternalApprovals.mockResolvedValue([
      { ...baseApproval, status: "assigned", assigned_to_user_id: employee.id, assigned_to_name: "employee", rejection_reason: "Missing a signature page." },
    ]);
    renderPanel(employee);
    await openApproval("FIRE-NOC");
    expect(await screen.findByText(/Missing a signature page\./)).toBeInTheDocument();
  });

  it("tells the assignee their submitted approval is waiting on Admin, with no employee decision controls", async () => {
    taskExecutionApi.listExternalApprovals.mockResolvedValue([
      { ...baseApproval, status: "submitted", assigned_to_user_id: employee.id, assigned_to_name: "employee" },
    ]);
    renderPanel(employee);
    await openApproval("FIRE-NOC");
    expect(await screen.findByText("Waiting on Admin review.")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Approve" })).not.toBeInTheDocument();
  });

  // ---- decision (Admin only) ----------------------------------------------

  it("offers Approve and a Reject/Request Changes action to Admin on a submitted approval", async () => {
    taskExecutionApi.listExternalApprovals.mockResolvedValue([
      { ...baseApproval, status: "submitted", assigned_to_user_id: employee.id, assigned_to_name: "employee" },
    ]);
    renderPanel(admin);
    await openApproval("FIRE-NOC");
    expect(await screen.findByRole("button", { name: "Approve" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /reject.*request changes/i })).toBeInTheDocument();
  });

  // The gap this closes: without a rendered submission history, Admin
  // deciding a submitted approval had no way to see what was actually
  // uploaded.
  it("shows the submission history with a download link for its evidence", async () => {
    taskExecutionApi.listExternalApprovals.mockResolvedValue([{
      ...baseApproval, status: "submitted", assigned_to_user_id: employee.id, assigned_to_name: "employee",
      submissions: [{
        id: "s1", submitted_by: employee.id, submitted_by_name: "employee", note: "NOC attached.",
        submitted_at: "2026-08-15T09:00:00Z",
        evidence: [{ id: "e1", file_id: "f1", evidence_type: "document", caption: null, original_filename: "noc.pdf", mime_type: "application/pdf", size_bytes: 1024 }],
      }],
    }]);
    renderPanel(admin);
    await openApproval("FIRE-NOC");
    expect(await screen.findByText("NOC attached.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /noc\.pdf/i })).toBeInTheDocument();
  });

  it("downloads an evidence file when its link is clicked", async () => {
    taskExecutionApi.listExternalApprovals.mockResolvedValue([{
      ...baseApproval, status: "submitted", assigned_to_user_id: employee.id, assigned_to_name: "employee",
      submissions: [{
        id: "s1", submitted_by: employee.id, submitted_by_name: "employee", note: null,
        submitted_at: "2026-08-15T09:00:00Z",
        evidence: [{ id: "e1", file_id: "f1", evidence_type: "document", caption: null, original_filename: "noc.pdf", mime_type: "application/pdf", size_bytes: 1024 }],
      }],
    }]);
    taskExecutionApi.downloadExternalApprovalEvidence.mockResolvedValue({ blob: new Blob(["x"]), filename: "noc.pdf" });
    renderPanel(admin);
    await openApproval("FIRE-NOC");
    fireEvent.click(await screen.findByRole("button", { name: /noc\.pdf/i }));
    await waitFor(() => expect(taskExecutionApi.downloadExternalApprovalEvidence).toHaveBeenCalledWith("p1", "a1", "f1"));
  });

  it("does not offer PM a decision action, unlike the old PM-fallback rule", async () => {
    taskExecutionApi.listExternalApprovals.mockResolvedValue([
      { ...baseApproval, status: "submitted", assigned_to_user_id: employee.id, assigned_to_name: "employee" },
    ]);
    renderPanel(pm);
    await openApproval("FIRE-NOC");
    expect(screen.queryByRole("button", { name: "Approve" })).not.toBeInTheDocument();
  });

  it("cannot submit a rejection without a reason", async () => {
    taskExecutionApi.listExternalApprovals.mockResolvedValue([
      { ...baseApproval, status: "submitted", assigned_to_user_id: employee.id, assigned_to_name: "employee" },
    ]);
    renderPanel(admin);
    await openApproval("FIRE-NOC");
    fireEvent.click(await screen.findByRole("button", { name: /reject.*request changes/i }));
    const confirm = await screen.findByRole("button", { name: "Confirm rejection" });
    expect(confirm).toBeDisabled();
    fireEvent.change(screen.getByPlaceholderText(/explain why this approval is being refused/i), { target: { value: "  " } });
    expect(confirm).toBeDisabled();
    expect(taskExecutionApi.decideExternalApproval).not.toHaveBeenCalled();
  });

  it("records a rejection (send-back) once a reason is given", async () => {
    taskExecutionApi.listExternalApprovals.mockResolvedValue([
      { ...baseApproval, status: "submitted", assigned_to_user_id: employee.id, assigned_to_name: "employee" },
    ]);
    taskExecutionApi.decideExternalApproval.mockResolvedValue({});
    renderPanel(admin);
    await openApproval("FIRE-NOC");
    fireEvent.click(await screen.findByRole("button", { name: /reject.*request changes/i }));
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
    await openApproval("FIRE-NOC");
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
    await openApproval("FIRE-NOC");
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
    await openApproval("FIRE-NOC");
    expect((await screen.findAllByText(/only an Admin can assign or decide/i)).length).toBeGreaterThan(0);
  });

  it("offers no decision actions on an approval that is already approved", async () => {
    taskExecutionApi.listExternalApprovals.mockResolvedValue([
      { ...baseApproval, status: "approved", decided_by_name: "Priya", decided_at: "2026-08-10T09:00:00Z" },
    ]);
    renderPanel(admin);
    expect(await screen.findByText("Fire NOC")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Approve" })).not.toBeInTheDocument();
    await openApproval("FIRE-NOC");
    expect(await screen.findByText(/by Priya/)).toBeInTheDocument();
  });

  // R10: an unresolved approval links no tasks, so it can never surface as a
  // task's readiness reason. This panel is one of the only places it is
  // visible - shown directly on the row, not gated behind selection.
  it("labels an approval whose coverage could not be resolved, and shows the prose, directly on the row", async () => {
    taskExecutionApi.listExternalApprovals.mockResolvedValue([
      { ...baseApproval, coverage_state: "unresolved", coverage_text: "All electrical works", covered_task_ids: [] },
    ]);
    renderPanel(admin);
    const table = await screen.findByRole("table");
    expect(within(table).getByText("Coverage unresolved")).toBeInTheDocument();
    expect(within(table).getByText(/All electrical works/)).toBeInTheDocument();
  });

  it("shows a Blocking chip for a blocking approval that has not yet been approved", async () => {
    taskExecutionApi.listExternalApprovals.mockResolvedValue([{ ...baseApproval, blocking: true, status: "unassigned" }]);
    renderPanel(admin);
    const table = await screen.findByRole("table");
    expect(within(table).getByText("Blocking")).toBeInTheDocument();
  });

  it("does not show a Blocking chip once an approval has been approved", async () => {
    taskExecutionApi.listExternalApprovals.mockResolvedValue([{ ...baseApproval, blocking: true, status: "approved", decided_by_name: "Priya", decided_at: "2026-08-10T09:00:00Z" }]);
    renderPanel(admin);
    const table = await screen.findByRole("table");
    await within(table).findByText("Fire NOC");
    expect(within(table).queryByText("Blocking")).not.toBeInTheDocument();
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

  it("shows 6 approval rows by default, then Load More/Show Less paginate the rest", async () => {
    taskExecutionApi.listExternalApprovals.mockResolvedValue(
      Array.from({ length: 8 }, (_, i) => ({ ...baseApproval, id: `a${i}`, gate_code: `GATE-${i}`, gate_name: `Gate ${i}` })),
    );
    renderPanel(admin);

    const bodyRows = () => screen.getAllByRole("row").filter(row => within(row).queryAllByRole("cell").length > 0);
    await waitFor(() => expect(bodyRows()).toHaveLength(6));
    expect(screen.queryByText("Show Less")).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Load More" }));
    await waitFor(() => expect(bodyRows()).toHaveLength(8));
    expect(screen.queryByRole("button", { name: "Load More" })).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Show Less" }));
    await waitFor(() => expect(bodyRows()).toHaveLength(6));
  });
});
