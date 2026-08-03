import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { projectsApi } from "../../api/projectsApi";
import { PendingRoleChangesPanel } from "./components/PendingRoleChangesPanel";

vi.mock("../../api/projectsApi", () => ({ projectsApi: {
  roleChanges: vi.fn(), reassignmentRequired: vi.fn(), approveRoleChange: vi.fn(), rejectRoleChange: vi.fn(),
} }));

const pendingChange = {
  id: "rc1", project_id: "p1", role_type: "site_supervisor", replacement_employee_id: "e1",
  replacement_name: "Priya Singh", change_type: "replacement", reason_code: "Supervisor unavailable.",
  status: "pending", requested_by: "u1", requested_at: "2026-08-02T00:00:00Z",
};

beforeEach(() => {
  vi.clearAllMocks();
  projectsApi.roleChanges.mockResolvedValue([]);
  projectsApi.reassignmentRequired.mockResolvedValue([]);
});

describe("PendingRoleChangesPanel", () => {
  it("renders nothing for a viewer with no pending items and no act permission", async () => {
    const { container } = render(<PendingRoleChangesPanel projectId="p1" user={{ role: "internal_employee" }} onChanged={vi.fn()}/>);
    await waitFor(() => expect(projectsApi.roleChanges).toHaveBeenCalledWith("p1", "pending"));
    expect(container).toBeEmptyDOMElement();
  });

  it("shows a Reassignment Required alert when a role is marked unavailable", async () => {
    projectsApi.reassignmentRequired.mockResolvedValue([{ membership_id: "m1", project_id: "p1", role_type: "site_supervisor", employee_id: "e2", availability: "unavailable" }]);
    render(<PendingRoleChangesPanel projectId="p1" user={{ role: "admin" }} onChanged={vi.fn()}/>);
    expect(await screen.findByText("Reassignment required")).toBeInTheDocument();
    expect(screen.getByText(/Site Supervisor/)).toBeInTheDocument();
  });

  it("lists a pending role change and approves it", async () => {
    projectsApi.roleChanges.mockResolvedValue([pendingChange]);
    projectsApi.approveRoleChange.mockResolvedValue({});
    const onChanged = vi.fn();
    render(<PendingRoleChangesPanel projectId="p1" user={{ role: "admin" }} onChanged={onChanged}/>);
    expect(await screen.findByText("Pending role changes")).toBeInTheDocument();
    expect(screen.getByText("Priya Singh", { exact: false })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Approve" }));
    await waitFor(() => expect(projectsApi.approveRoleChange).toHaveBeenCalledWith("p1", "rc1"));
    await waitFor(() => expect(onChanged).toHaveBeenCalledTimes(1));
  });

  it("requires at least 4 characters before rejecting", async () => {
    projectsApi.roleChanges.mockResolvedValue([pendingChange]);
    render(<PendingRoleChangesPanel projectId="p1" user={{ role: "admin" }} onChanged={vi.fn()}/>);
    await screen.findByText("Pending role changes");
    const rejectButton = screen.getByRole("button", { name: "Reject" });
    expect(rejectButton).toBeDisabled();
    fireEvent.change(screen.getByPlaceholderText(/reason \(required\)/i), { target: { value: "No longer needed." } });
    expect(rejectButton).toBeEnabled();
    fireEvent.click(rejectButton);
    await waitFor(() => expect(projectsApi.rejectRoleChange).toHaveBeenCalledWith("p1", "rc1", "No longer needed."));
  });

  it("hides approve/reject controls for a role that cannot act", async () => {
    projectsApi.roleChanges.mockResolvedValue([pendingChange]);
    render(<PendingRoleChangesPanel projectId="p1" user={{ role: "supervisor" }} onChanged={vi.fn()}/>);
    expect(await screen.findByText("Pending role changes")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Approve" })).not.toBeInTheDocument();
  });

  it("lets a project_manager act on a site_supervisor replacement", async () => {
    projectsApi.roleChanges.mockResolvedValue([pendingChange]);
    render(<PendingRoleChangesPanel projectId="p1" user={{ role: "project_manager" }} onChanged={vi.fn()}/>);
    expect(await screen.findByRole("button", { name: "Approve" })).toBeInTheDocument();
  });

  it("hides approve/reject from a project_manager for a project_manager replacement (BR-007: Admin-only)", async () => {
    const pmChange = { ...pendingChange, id: "rc2", role_type: "project_manager" };
    projectsApi.roleChanges.mockResolvedValue([pmChange]);
    render(<PendingRoleChangesPanel projectId="p1" user={{ role: "project_manager" }} onChanged={vi.fn()}/>);
    expect(await screen.findByText("Pending role changes")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Approve" })).not.toBeInTheDocument();
  });

  it("lets admin act on a project_manager replacement", async () => {
    const pmChange = { ...pendingChange, id: "rc2", role_type: "project_manager" };
    projectsApi.roleChanges.mockResolvedValue([pmChange]);
    render(<PendingRoleChangesPanel projectId="p1" user={{ role: "admin" }} onChanged={vi.fn()}/>);
    expect(await screen.findByRole("button", { name: "Approve" })).toBeInTheDocument();
  });
});
