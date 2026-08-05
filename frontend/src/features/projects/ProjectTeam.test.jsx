import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { projectsApi } from "../../api/projectsApi";
import { ProjectDetailModal } from "./components/ProjectDetailModal";

vi.mock("../../api/projectsApi", () => ({ projectsApi: {
  detail: vi.fn(), activity: vi.fn(), setMembership: vi.fn(),
  roleChanges: vi.fn(), reassignmentRequired: vi.fn(),
} }));

const references = {
  project_managers: [{ employee_id: "emp-pm-1", name: "Priya PM", designation: "Project Manager" }],
  supervisors: [{ employee_id: "emp-sup-1", name: "Sanjay Supervisor", designation: "Site Supervisor" }],
  internal_employees: [{ employee_id: "emp-ie-1", name: "Rahul Employee", designation: "Site Engineer" }],
};

const baseProject = {
  id: "p1", code: "P1", name: "Test project", client_name: "Client", site_address: "Site",
  start_date: "2026-08-01", target_handover_date: null, template_version_id: "v1", status: "draft",
  memberships: [{ id: "m-pm", employee_id: "emp-pm-existing", user_id: "u-pm-existing", name: "Existing PM", project_role: "project_manager" }],
  setup: { has_project_manager: true, has_site_supervisor: false, has_template: true, has_target_handover_date: false, activation_ready: false },
};

async function openTeamTab(user) {
  render(<ProjectDetailModal projectId="p1" references={references} user={user} templates={[]} onClose={vi.fn()} onEdit={vi.fn()} onChanged={vi.fn()} onDeleted={vi.fn()}/>);
  await screen.findByText("Test project");
  fireEvent.click(screen.getByRole("button", { name: /team/i }));
  await screen.findByText("Add team member");
}

beforeEach(() => {
  vi.clearAllMocks();
  projectsApi.detail.mockResolvedValue(baseProject);
  projectsApi.activity.mockResolvedValue([]);
  projectsApi.roleChanges.mockResolvedValue([]);
  projectsApi.reassignmentRequired.mockResolvedValue([]);
});

describe("Add team member", () => {
  it("lets an Admin add an internal employee to the project team", async () => {
    projectsApi.setMembership.mockResolvedValue({ id: "mem-new", employee_id: "emp-ie-1", project_role: "internal_employee", starts_at: "2026-08-05T00:00:00Z" });
    await openTeamTab({ role: "admin", id: "u-admin" });

    fireEvent.change(screen.getByLabelText("Role"), { target: { value: "internal_employee" } });
    fireEvent.change(screen.getByLabelText("Person"), { target: { value: "emp-ie-1" } });
    fireEvent.change(screen.getByLabelText("Reason"), { target: { value: "Assigned to support execution." } });
    fireEvent.click(screen.getByRole("button", { name: "Add" }));

    await waitFor(() => expect(projectsApi.setMembership).toHaveBeenCalledWith("p1", {
      employee_id: "emp-ie-1", project_role: "internal_employee", reason: "Assigned to support execution.",
    }));
    expect(await screen.findByText("Added to the project team.")).toBeInTheDocument();
  });

  it("shows a pending-approval notice when adding an accountable role returns a role-change request", async () => {
    projectsApi.setMembership.mockResolvedValue({ id: "change-1", status: "pending", role_type: "project_manager" });
    await openTeamTab({ role: "admin", id: "u-admin" });

    fireEvent.change(screen.getByLabelText("Role"), { target: { value: "project_manager" } });
    fireEvent.change(screen.getByLabelText("Person"), { target: { value: "emp-pm-1" } });
    fireEvent.change(screen.getByLabelText("Reason"), { target: { value: "Replacing outgoing PM." } });
    fireEvent.click(screen.getByRole("button", { name: "Add" }));

    expect(await screen.findByText("Replacement request submitted - pending approval.")).toBeInTheDocument();
  });

  it("only offers Internal Employee to a Supervisor, matching the backend's own permission rule", async () => {
    const project = { ...baseProject, memberships: [...baseProject.memberships, { id: "m-sup", employee_id: "emp-sup-existing", user_id: "u-sup", name: "Existing Supervisor", project_role: "site_supervisor" }] };
    projectsApi.detail.mockResolvedValue(project);
    await openTeamTab({ role: "supervisor", id: "u-sup" });

    const roleSelect = screen.getByLabelText("Role");
    const optionValues = Array.from(roleSelect.options).map(option => option.value);
    expect(optionValues).toEqual(["internal_employee"]);
  });

  it("hides the Add team member section for a role with no assignable options", async () => {
    render(<ProjectDetailModal projectId="p1" references={references} user={{ role: "internal_employee", id: "u-ie" }} templates={[]} onClose={vi.fn()} onEdit={vi.fn()} onChanged={vi.fn()} onDeleted={vi.fn()}/>);
    await screen.findByText("Test project");
    fireEvent.click(screen.getByRole("button", { name: /team/i }));
    await screen.findByText("Memberships");
    expect(screen.queryByText("Add team member")).not.toBeInTheDocument();
  });
});
