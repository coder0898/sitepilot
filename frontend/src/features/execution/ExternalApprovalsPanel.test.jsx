import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { projectsApi } from "../../api/projectsApi";
import { taskExecutionApi } from "../../api/taskExecutionApi";
import { ExternalApprovalsPanel } from "./components/ExternalApprovalsPanel";

vi.mock("../../api/taskExecutionApi", () => ({ taskExecutionApi: {
  listExternalApprovals: vi.fn(), decideExternalApproval: vi.fn(), list: vi.fn(), detail: vi.fn(),
} }));
vi.mock("../../api/projectsApi", () => ({ projectsApi: { detail: vi.fn(), externalGates: vi.fn() } }));

const gate = (applicability_state = "pending_review") => ({ id: `g-${Math.random()}`, applicability_state });

const pending = {
  id: "a1", project_id: "p1", project_gate_id: "g1", gate_code: "FIRE-NOC", gate_name: "Fire NOC",
  status: "pending", blocking: true, coverage_state: "exact", coverage_text: null,
  covered_task_ids: ["t1", "t2"], decided_by: null, decided_by_name: null, decided_at: null,
};

// Authority here is the actor's membership of THIS project, not their global
// role - the same fact ProjectGateDecisionService._require_approver resolves.
const projectManager = { id: "u-pm", role: "project_manager" };
const supervisor = { id: "u-sup", role: "supervisor" };
const admin = { id: "u-adm", role: "admin" };
const membership = (user, projectRole) => ({ id: `m-${user.id}`, user_id: user.id, project_role: projectRole, ends_at: null });
const projectWith = (...memberships) => ({ id: "p1", memberships });
const pmProject = projectWith(membership(projectManager, "project_manager"), membership(supervisor, "site_supervisor"));

const renderPanel = (user, props = {}) => render(
  <ExternalApprovalsPanel projectId="p1" project={pmProject} user={user} {...props}/>,
);

beforeEach(() => {
  vi.clearAllMocks();
  taskExecutionApi.listExternalApprovals.mockResolvedValue([pending]);
  projectsApi.externalGates.mockResolvedValue({ items: [gate("applicable")] });
});

describe("ExternalApprovalsPanel", () => {
  it("reads the execution-layer approvals, not the planning-layer gates", async () => {
    renderPanel(projectManager);
    expect(await screen.findByText("Fire NOC")).toBeInTheDocument();
    expect(taskExecutionApi.listExternalApprovals).toHaveBeenCalledWith("p1");
  });

  it("offers approve and reject to the project's PM on a pending approval", async () => {
    renderPanel(projectManager);
    expect(await screen.findByRole("button", { name: "Approve" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Reject" })).toBeInTheDocument();
  });

  it("offers them to an Admin regardless of membership", async () => {
    renderPanel(admin, { project: projectWith() });
    expect(await screen.findByRole("button", { name: "Approve" })).toBeInTheDocument();
  });

  // Read access is deliberately wider than write: a Supervisor must see what
  // is holding up their site without being offered an action that would 403.
  it("shows a Supervisor the approval but no decision actions", async () => {
    renderPanel(supervisor);
    expect(await screen.findByText("Fire NOC")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Approve" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Reject" })).not.toBeInTheDocument();
    expect(screen.getByText(/only the project's PM or an Admin/i)).toBeInTheDocument();
  });

  it("offers no actions on an approval that is already decided", async () => {
    taskExecutionApi.listExternalApprovals.mockResolvedValue([
      { ...pending, status: "approved", decided_by_name: "Priya", decided_at: "2026-08-10T09:00:00Z" },
    ]);
    renderPanel(projectManager);
    expect(await screen.findByText("Fire NOC")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Approve" })).not.toBeInTheDocument();
    expect(screen.getByText(/by Priya/)).toBeInTheDocument();
  });

  // R10: an unresolved approval links no tasks, so it can never surface as a
  // task's readiness reason. This panel is the only place it is visible.
  it("labels an approval whose coverage could not be resolved, and shows the prose", async () => {
    taskExecutionApi.listExternalApprovals.mockResolvedValue([
      { ...pending, coverage_state: "unresolved", coverage_text: "All electrical works", covered_task_ids: [] },
    ]);
    renderPanel(projectManager);
    expect(await screen.findByText("Coverage unresolved")).toBeInTheDocument();
    expect(screen.getByText(/All electrical works/)).toBeInTheDocument();
  });

  it("cannot submit a rejection without a reason", async () => {
    renderPanel(projectManager);
    fireEvent.click(await screen.findByRole("button", { name: "Reject" }));
    const confirm = await screen.findByRole("button", { name: "Confirm rejection" });
    expect(confirm).toBeDisabled();
    fireEvent.change(screen.getByPlaceholderText(/explain why this approval is being refused/i), { target: { value: "  " } });
    expect(confirm).toBeDisabled();
    expect(taskExecutionApi.decideExternalApproval).not.toHaveBeenCalled();
  });

  it("records a rejection once a reason is given", async () => {
    taskExecutionApi.decideExternalApproval.mockResolvedValue({});
    renderPanel(projectManager);
    fireEvent.click(await screen.findByRole("button", { name: "Reject" }));
    fireEvent.change(await screen.findByPlaceholderText(/explain why this approval is being refused/i), { target: { value: "Drawings rejected by the authority." } });
    fireEvent.click(screen.getByRole("button", { name: "Confirm rejection" }));
    await waitFor(() => expect(taskExecutionApi.decideExternalApproval).toHaveBeenCalledWith(
      "p1", "a1", { decision: "rejected", reason: "Drawings rejected by the authority." },
    ));
  });

  it("records an approval without requiring remarks", async () => {
    taskExecutionApi.decideExternalApproval.mockResolvedValue({});
    renderPanel(projectManager);
    fireEvent.click(await screen.findByRole("button", { name: "Approve" }));
    const confirm = await screen.findByRole("button", { name: "Confirm approval" });
    expect(confirm).toBeEnabled();
    fireEvent.click(confirm);
    await waitFor(() => expect(taskExecutionApi.decideExternalApproval).toHaveBeenCalledWith(
      "p1", "a1", { decision: "approved", reason: null },
    ));
  });

  it("refetches so the decided approval shows its new status", async () => {
    taskExecutionApi.decideExternalApproval.mockResolvedValue({});
    renderPanel(projectManager);
    fireEvent.click(await screen.findByRole("button", { name: "Approve" }));
    fireEvent.click(await screen.findByRole("button", { name: "Confirm approval" }));
    await waitFor(() => expect(taskExecutionApi.listExternalApprovals).toHaveBeenCalledTimes(2));
  });

  it("shows a refused decision inline and leaves the approval unchanged", async () => {
    taskExecutionApi.decideExternalApproval.mockRejectedValue(new Error("This approval has already been decided."));
    renderPanel(projectManager);
    fireEvent.click(await screen.findByRole("button", { name: "Approve" }));
    fireEvent.click(await screen.findByRole("button", { name: "Confirm approval" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(/already been decided/i);
    // Modal still open and nothing refetched - the approval is as it was.
    expect(screen.getByRole("button", { name: "Confirm approval" })).toBeInTheDocument();
    expect(taskExecutionApi.listExternalApprovals).toHaveBeenCalledTimes(1);
  });

  it("surfaces a failed load rather than rendering an empty list as if there were none", async () => {
    taskExecutionApi.listExternalApprovals.mockRejectedValue(new Error("Server unavailable"));
    renderPanel(projectManager);
    expect(await screen.findByText("Server unavailable")).toBeInTheDocument();
    expect(screen.queryByText(/No external approvals were instantiated/i)).not.toBeInTheDocument();
  });

  it("reports a project whose gates were all ruled out as genuinely having none", async () => {
    taskExecutionApi.listExternalApprovals.mockResolvedValue([]);
    projectsApi.externalGates.mockResolvedValue({ items: [gate("not_applicable"), gate("not_applicable")] });
    renderPanel(projectManager);
    expect(await screen.findByText(/No external approvals apply to this project/i)).toBeInTheDocument();
  });

  // The screen a PM actually hits: 32 gates exist, none has been ruled on, so
  // nothing was instantiated. Saying only "none were instantiated" describes
  // our mechanism and leaves the user believing the project has no external
  // approvals, when it has 32 sitting undecided in setup.
  describe("gates still awaiting an applicability decision", () => {
    beforeEach(() => {
      taskExecutionApi.listExternalApprovals.mockResolvedValue([]);
      projectsApi.externalGates.mockResolvedValue({ items: Array.from({ length: 32 }, () => gate()) });
    });

    it("says how many are awaiting review and what unblocks them", async () => {
      renderPanel(projectManager);
      expect(await screen.findByText(/32 external approvals are awaiting applicability review/i)).toBeInTheDocument();
      expect(screen.getByText(/decides, in this project's setup/i)).toBeInTheDocument();
    });

    it("does not claim the project has none", async () => {
      renderPanel(projectManager);
      await screen.findByText(/awaiting applicability review/i);
      expect(screen.queryByText(/No external approvals apply to this project/i)).not.toBeInTheDocument();
    });

    it("reassures that undecided gates are not holding work up", async () => {
      renderPanel(projectManager);
      expect(await screen.findByText(/they hold nothing up/i)).toBeInTheDocument();
    });

    it("reads naturally for a single undecided gate", async () => {
      projectsApi.externalGates.mockResolvedValue({ items: [gate()] });
      renderPanel(projectManager);
      expect(await screen.findByText(/1 external approval is awaiting applicability review/i)).toBeInTheDocument();
      expect(screen.getByText(/it holds nothing up/i)).toBeInTheDocument();
    });
  });

  it("warns about undecided gates even when some approvals already exist", async () => {
    projectsApi.externalGates.mockResolvedValue({ items: [gate("applicable"), gate(), gate()] });
    renderPanel(projectManager);
    expect(await screen.findByText("Fire NOC")).toBeInTheDocument();
    expect(screen.getByText(/2 external approvals are awaiting applicability review/i)).toBeInTheDocument();
  });

  // This read only enriches an explanation, so losing it must never cost the
  // user the approvals they can actually act on.
  it("still renders the approvals when the planning-gate read fails", async () => {
    projectsApi.externalGates.mockRejectedValue(new Error("gates unavailable"));
    renderPanel(projectManager);
    expect(await screen.findByText("Fire NOC")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Approve" })).toBeInTheDocument();
    expect(screen.queryByText(/awaiting applicability review/i)).not.toBeInTheDocument();
  });
});
