import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { useState } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { projectsApi } from "../../api/projectsApi";
import { ProjectWorkspace } from "./components/ProjectWorkspace";

vi.mock("../../api/projectsApi", () => ({ projectsApi: {
  detail: vi.fn(), activity: vi.fn(), setMembership: vi.fn(),
  roleChanges: vi.fn(), reassignmentRequired: vi.fn(),
  dependencies: vi.fn(), externalGates: vi.fn(),
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

// ProjectsPage owns the pane in the URL; this mirrors that ownership so the
// tests still exercise real tab navigation rather than a fixed pane prop.
function Harness({ user }) {
  const [pane, setPane] = useState("overview");
  return <ProjectWorkspace
    projectId="p1" references={references} templates={[]} user={user}
    pane={pane} onPaneChange={setPane}
    onEdit={vi.fn()} onChanged={vi.fn().mockResolvedValue(undefined)} onDeleted={vi.fn()}
  />;
}

async function openTeamTab(user) {
  render(<Harness user={user}/>);
  await screen.findByText("Test project");
  fireEvent.click(screen.getByRole("button", { name: /^team$/i }));
  await screen.findByText("Add team member");
}

beforeEach(() => {
  vi.clearAllMocks();
  projectsApi.detail.mockResolvedValue(baseProject);
  projectsApi.activity.mockResolvedValue([]);
  projectsApi.roleChanges.mockResolvedValue([]);
  projectsApi.reassignmentRequired.mockResolvedValue([]);
  projectsApi.dependencies.mockResolvedValue({ total: 0, items: [] });
  projectsApi.externalGates.mockResolvedValue({ total: 0, items: [] });
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
    render(<Harness user={{ role: "internal_employee", id: "u-ie" }}/>);
    await screen.findByText("Test project");
    fireEvent.click(screen.getByRole("button", { name: /^team$/i }));
    await screen.findByText("Memberships");
    expect(screen.queryByText("Add team member")).not.toBeInTheDocument();
  });

  it("hides the planning panes from a Supervisor, matching the backend's template-role guard", async () => {
    render(<Harness user={{ role: "supervisor", id: "u-sup" }}/>);
    await screen.findByText("Test project");
    expect(screen.queryByRole("button", { name: /template review/i })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /external gates/i })).not.toBeInTheDocument();
  });
});
