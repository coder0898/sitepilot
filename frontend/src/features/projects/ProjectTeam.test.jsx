import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { useState } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { projectsApi } from "../../api/projectsApi";
import { ProjectWorkspace } from "./components/ProjectWorkspace";

vi.mock("../../api/projectsApi", () => ({ projectsApi: {
  detail: vi.fn(), activity: vi.fn(), setMembership: vi.fn(), endMembership: vi.fn(), requestRoleChange: vi.fn(),
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

describe("Remove team member", () => {
  const projectWithInternalEmployee = {
    ...baseProject,
    memberships: [...baseProject.memberships, { id: "m-ie", employee_id: "emp-ie-existing", user_id: "u-ie-existing", name: "Existing Employee", project_role: "internal_employee" }],
  };

  it("lets an Admin remove an Internal Employee, with a reason, and refreshes the team", async () => {
    projectsApi.detail.mockResolvedValue(projectWithInternalEmployee);
    projectsApi.endMembership.mockResolvedValue({ id: "m-ie", ends_at: "2026-09-02T00:00:00Z" });
    await openTeamTab({ role: "admin", id: "u-admin" });

    // Draft + Admin also puts a Remove button on the PM row (index 0) - see
    // the dedicated PM-removal test below. Membership order mirrors
    // projectWithInternalEmployee.memberships: [PM, Internal Employee].
    fireEvent.click(screen.getAllByRole("button", { name: "Remove" })[1]);
    const dialog = await screen.findByRole("dialog", { name: "Remove Existing Employee" });
    fireEvent.change(within(dialog).getByLabelText("Reason"), { target: { value: "No longer needed on site." } });
    fireEvent.click(within(dialog).getByRole("button", { name: "Remove" }));

    await waitFor(() => expect(projectsApi.endMembership).toHaveBeenCalledWith("p1", "m-ie", "No longer needed on site."));
    expect(projectsApi.detail).toHaveBeenCalledTimes(2);
  });

  it("hides Remove from an Internal Employee viewing their own project team", async () => {
    projectsApi.detail.mockResolvedValue(projectWithInternalEmployee);
    render(<Harness user={{ role: "internal_employee", id: "u-ie-existing" }}/>);
    await screen.findByText("Test project");
    fireEvent.click(screen.getByRole("button", { name: /^team$/i }));
    await screen.findByText("Memberships");

    expect(screen.queryByRole("button", { name: "Remove" })).not.toBeInTheDocument();
  });

  it("lets an Admin remove a Project Manager directly while the project is still draft - end_membership allows it there", async () => {
    projectsApi.detail.mockResolvedValue(projectWithInternalEmployee); // status: draft
    projectsApi.endMembership.mockResolvedValue({ id: "m-pm", ends_at: "2026-09-02T00:00:00Z" });
    await openTeamTab({ role: "admin", id: "u-admin" });

    // Both the PM row and the Internal Employee row offer Remove on a draft project.
    expect(screen.getAllByRole("button", { name: "Remove" })).toHaveLength(2);

    fireEvent.click(screen.getAllByRole("button", { name: "Remove" })[0]);
    const dialog = await screen.findByRole("dialog", { name: "Remove Existing PM" });
    fireEvent.change(within(dialog).getByLabelText("Reason"), { target: { value: "Reassigning before activation." } });
    fireEvent.click(within(dialog).getByRole("button", { name: "Remove" }));

    await waitFor(() => expect(projectsApi.endMembership).toHaveBeenCalledWith("p1", "m-pm", "Reassigning before activation."));
  });

  it("also lets an Admin remove a Project Manager directly on an on_hold project - end_membership only blocks it when active", async () => {
    const onHoldProject = { ...projectWithInternalEmployee, status: "on_hold" };
    projectsApi.detail.mockResolvedValue(onHoldProject);
    projectsApi.endMembership.mockResolvedValue({ id: "m-pm", ends_at: "2026-09-02T00:00:00Z" });
    await openTeamTab({ role: "admin", id: "u-admin" });

    expect(screen.getAllByRole("button", { name: "Remove" })).toHaveLength(2);
    fireEvent.click(screen.getAllByRole("button", { name: "Remove" })[0]);
    const dialog = await screen.findByRole("dialog", { name: "Remove Existing PM" });
    fireEvent.change(within(dialog).getByLabelText("Reason"), { target: { value: "Project paused, PM reassigned." } });
    fireEvent.click(within(dialog).getByRole("button", { name: "Remove" }));

    await waitFor(() => expect(projectsApi.endMembership).toHaveBeenCalledWith("p1", "m-pm", "Project paused, PM reassigned."));
  });

  it("does not offer direct Remove on Project Manager/Supervisor rows once the project is active - only the replace flow applies", async () => {
    const activeProject = { ...projectWithInternalEmployee, status: "active" };
    projectsApi.detail.mockResolvedValue(activeProject);
    await openTeamTab({ role: "admin", id: "u-admin" });

    // Only the Internal Employee row offers Remove; PM stays replace-only.
    expect(screen.getAllByRole("button", { name: "Remove" })).toHaveLength(1);
  });

  it("lets the project's own PM (not just Admin) remove a Supervisor directly while draft, matching the backend's Supervisor-replacement hierarchy", async () => {
    const draftWithSupervisor = {
      ...projectWithInternalEmployee,
      memberships: [...projectWithInternalEmployee.memberships, { id: "m-sup", employee_id: "emp-sup-existing", user_id: "u-pm-existing", name: "Existing Supervisor", project_role: "site_supervisor" }],
    };
    projectsApi.detail.mockResolvedValue(draftWithSupervisor);
    projectsApi.endMembership.mockResolvedValue({ id: "m-sup", ends_at: "2026-09-02T00:00:00Z" });
    // "u-pm-existing" is this project's own PM (matches m-pm's user_id above), not a global Admin.
    await openTeamTab({ role: "project_manager", id: "u-pm-existing" });

    // A PM cannot end their own PM membership (Admin-only), so only the
    // Internal Employee (index 0) and Supervisor (index 1) rows offer Remove -
    // membership order: [PM, Internal Employee, Supervisor].
    fireEvent.click(screen.getAllByRole("button", { name: "Remove" })[1]);
    const dialog = await screen.findByRole("dialog", { name: "Remove Existing Supervisor" });
    fireEvent.change(within(dialog).getByLabelText("Reason"), { target: { value: "Supervisor reassigned to another site." } });
    fireEvent.click(within(dialog).getByRole("button", { name: "Remove" }));

    await waitFor(() => expect(projectsApi.endMembership).toHaveBeenCalledWith("p1", "m-sup", "Supervisor reassigned to another site."));
  });
});

describe("Replace (Change) Project Manager / Supervisor", () => {
  it("offers Change for the Supervisor to the project's own PM on an active project, matching the backend's request_role_change hierarchy", async () => {
    const activeProjectWithSupervisor = {
      ...baseProject,
      status: "active",
      memberships: [...baseProject.memberships, { id: "m-sup", employee_id: "emp-sup-existing", user_id: "u-sup-existing", name: "Existing Supervisor", project_role: "site_supervisor" }],
    };
    projectsApi.detail.mockResolvedValue(activeProjectWithSupervisor);
    // "u-pm-existing" matches baseProject's PM membership user_id - this actor is the project's own PM.
    render(<Harness user={{ role: "project_manager", id: "u-pm-existing" }}/>);
    await screen.findByText("Test project");
    fireEvent.click(screen.getByRole("button", { name: /^team$/i }));
    await screen.findByText("Memberships");

    // Only one Change button: for Supervisor. A PM cannot request their own replacement.
    expect(screen.getAllByRole("button", { name: "Change" })).toHaveLength(1);
  });

  it("does not offer Change to a Supervisor for their own role - only Admin or the project's PM can request it", async () => {
    const activeProjectWithSupervisor = {
      ...baseProject,
      status: "active",
      memberships: [...baseProject.memberships, { id: "m-sup", employee_id: "emp-sup-existing", user_id: "u-sup-existing", name: "Existing Supervisor", project_role: "site_supervisor" }],
    };
    projectsApi.detail.mockResolvedValue(activeProjectWithSupervisor);
    render(<Harness user={{ role: "supervisor", id: "u-sup-existing" }}/>);
    await screen.findByText("Test project");
    fireEvent.click(screen.getByRole("button", { name: /^team$/i }));
    await screen.findByText("Memberships");

    expect(screen.queryByRole("button", { name: "Change" })).not.toBeInTheDocument();
  });
});

describe("Vacate now, fill later", () => {
  const activeProjectWithSupervisor = {
    ...baseProject,
    status: "active",
    memberships: [...baseProject.memberships, { id: "m-sup", employee_id: "emp-sup-existing", user_id: "u-sup-existing", name: "Existing Supervisor", project_role: "site_supervisor" }],
  };

  it("offers a vacate mode alongside naming a replacement, when the role currently has a holder", async () => {
    projectsApi.detail.mockResolvedValue(activeProjectWithSupervisor);
    await openTeamTab({ role: "admin", id: "u-admin" });

    // Admin sees Change for both cards - [PM, Supervisor]; Supervisor's is index 1.
    fireEvent.click(screen.getAllByRole("button", { name: "Change" })[1]);
    const dialog = await screen.findByRole("dialog", { name: "Request Supervisor replacement" });
    expect(within(dialog).getByRole("button", { name: "Name a replacement" })).toBeInTheDocument();
    expect(within(dialog).getByRole("button", { name: "Vacate now, fill later" })).toBeInTheDocument();
  });

  it("submits a vacate request with no replacement named, and shows the pending-vacate confirmation", async () => {
    projectsApi.detail.mockResolvedValue(activeProjectWithSupervisor);
    projectsApi.requestRoleChange.mockResolvedValue({ id: "rc1", role_type: "site_supervisor", change_type: "vacate", status: "pending" });
    await openTeamTab({ role: "admin", id: "u-admin" });

    fireEvent.click(screen.getAllByRole("button", { name: "Change" })[1]);
    const dialog = await screen.findByRole("dialog", { name: "Request Supervisor replacement" });
    fireEvent.click(within(dialog).getByRole("button", { name: "Vacate now, fill later" }));
    fireEvent.change(within(dialog).getByLabelText("Reason"), { target: { value: "Supervisor has left the organisation." } });
    fireEvent.click(within(dialog).getByRole("button", { name: "Request vacate" }));

    await waitFor(() => expect(projectsApi.requestRoleChange).toHaveBeenCalledWith("p1", {
      role_type: "site_supervisor", change_type: "vacate", reason: "Supervisor has left the organisation.",
    }));
    expect(await screen.findByRole("dialog", { name: "Supervisor vacate requested" })).toBeInTheDocument();
  });

  it("hides the vacate option when the role is already unassigned - nothing to vacate", async () => {
    // status: active; only a PM membership - Supervisor is unassigned.
    const projectWithVacantSupervisor = { ...baseProject, status: "active" };
    projectsApi.detail.mockResolvedValue(projectWithVacantSupervisor);
    await openTeamTab({ role: "admin", id: "u-admin" });

    // Admin can see Change for both cards regardless of vacancy - [PM, Supervisor].
    fireEvent.click(screen.getAllByRole("button", { name: "Change" })[1]);
    const dialog = await screen.findByRole("dialog", { name: "Request Supervisor replacement" });
    expect(within(dialog).queryByRole("button", { name: "Vacate now, fill later" })).not.toBeInTheDocument();
  });
});
