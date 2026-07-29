import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { StrictMode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { projectsApi } from "../../api/projectsApi";
import { ProjectsPage } from "./ProjectsPage";

vi.mock("../../api/projectsApi", () => ({
  projectsApi: {
    list: vi.fn(), references: vi.fn(), publishedTemplates: vi.fn(), create: vi.fn(), update: vi.fn(),
  },
}));
vi.mock("./components/ProjectDetailModal", () => ({
  ProjectDetailModal: ({ projectId }) => <div data-testid="opened-project">{projectId}</div>,
}));

const references = {
  project_managers: [{ employee_id: "employee-pm", user_id: "user-pm", name: "Priya Manager", designation: "Project Manager" }],
  supervisors: [{ employee_id: "employee-supervisor", user_id: "user-supervisor", name: "Sameer Supervisor", designation: "Site Supervisor" }],
  internal_employees: [],
};
const templateResponse = {
  items: [{ version_id: "version-published", version_no: 2, template_name: "Workved 45-Day Template", duration_days: 45, status: "published", is_current_published: true }],
  pagination: { page: 1, page_size: 100, total: 1, total_pages: 1 },
};

function setup(role = "admin") {
  return render(<ProjectsPage user={{ role }} action={vi.fn(async operation => {
    try { await operation(); return { ok: true }; } catch (error) { return { ok: false, error: error.message }; }
  })}/>);
}

async function openForm(role = "admin") {
  setup(role);
  await screen.findByText("Create the first controlled project");
  fireEvent.click(screen.getByRole("button", { name: /new project/i }));
  return screen.findByRole("heading", { name: /create draft project/i });
}

function fillForm() {
  fireEvent.change(screen.getByLabelText("Project name"), { target: { value: "Mumbai HQ Fit-Out" } });
  fireEvent.change(screen.getByLabelText("Client"), { target: { value: "Acme India" } });
  fireEvent.change(screen.getByLabelText("Location"), { target: { value: "Lower Parel, Mumbai" } });
  fireEvent.change(screen.getByLabelText("Proposed start date"), { target: { value: "2026-08-10" } });
  fireEvent.change(screen.getByLabelText("Project Manager"), { target: { value: "user-pm" } });
  fireEvent.change(screen.getByLabelText("Supervisor"), { target: { value: "user-supervisor" } });
  fireEvent.change(screen.getByLabelText("Published template version"), { target: { value: "version-published" } });
}

beforeEach(() => {
  vi.clearAllMocks();
  projectsApi.list.mockResolvedValue([]);
  projectsApi.references.mockResolvedValue(references);
  projectsApi.publishedTemplates.mockResolvedValue(templateResponse);
});

describe("Admin draft project creation", () => {

  it("deduplicates initial project, role and template reference requests under StrictMode", async () => {
    render(<StrictMode><ProjectsPage user={{ role: "admin" }} action={vi.fn(async operation => {
      try { await operation(); return { ok: true }; } catch (error) { return { ok: false, error: error.message }; }
    })}/></StrictMode>);
    await screen.findByText("Create the first controlled project");
    expect(projectsApi.list).toHaveBeenCalledTimes(1);
    expect(projectsApi.references).toHaveBeenCalledTimes(1);
    expect(projectsApi.publishedTemplates).toHaveBeenCalledTimes(1);
  });

  it("loads the published template reference list for Super Admin fallback", async () => {
    await openForm("super_admin");
    expect(projectsApi.publishedTemplates).toHaveBeenCalledTimes(1);
    expect(screen.getByRole("option", { name: /Workved 45-Day Template.*Current/ })).toHaveValue("version-published");
  });

  it("renders active role selectors and published template options", async () => {
    await openForm();
    expect(screen.getByRole("option", { name: /Priya Manager/ })).toHaveValue("user-pm");
    expect(screen.getByRole("option", { name: /Sameer Supervisor/ })).toHaveValue("user-supervisor");
    expect(screen.getByRole("option", { name: /Workved 45-Day Template.*Current/ })).toHaveValue("version-published");
  });

  it("shows the approved template section before accountability and never hides an empty state", async () => {
    await openForm();
    const templateHeading = screen.getByText("Approved published template");
    const accountabilityHeading = screen.getByText("Accountability");
    expect(templateHeading.compareDocumentPosition(accountabilityHeading) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(screen.getByLabelText("Published template version")).toBeVisible();
  });

  it("submits the accepted backend contract and opens the returned project id", async () => {
    projectsApi.create.mockResolvedValue({ id: "project-created" });
    await openForm();
    fillForm();
    fireEvent.click(screen.getByRole("button", { name: /create draft/i }));

    await waitFor(() => expect(projectsApi.create).toHaveBeenCalledWith({
      name: "Mumbai HQ Fit-Out",
      client_name: "Acme India",
      site_address: "Lower Parel, Mumbai",
      start_date: "2026-08-10",
      project_manager_user_id: "user-pm",
      supervisor_user_id: "user-supervisor",
      template_version_id: "version-published",
    }));
    expect(await screen.findByTestId("opened-project")).toHaveTextContent("project-created");
  });

  it("prevents double submit and disables controls while pending", async () => {
    let resolveCreate;
    projectsApi.create.mockReturnValue(new Promise(resolve => { resolveCreate = resolve; }));
    await openForm();
    fillForm();
    const submit = screen.getByRole("button", { name: /create draft/i });
    fireEvent.click(submit);
    fireEvent.click(submit);
    expect(projectsApi.create).toHaveBeenCalledTimes(1);
    expect(submit).toBeDisabled();
    expect(screen.getByLabelText("Project name")).toBeDisabled();
    resolveCreate({ id: "project-pending" });
    expect(await screen.findByTestId("opened-project")).toHaveTextContent("project-pending");
  });

  it("shows field and API errors without closing the form", async () => {
    await openForm();
    fireEvent.click(screen.getByRole("button", { name: /create draft/i }));
    expect(await screen.findByText("Project name is required.")).toBeInTheDocument();
    expect(projectsApi.create).not.toHaveBeenCalled();

    fillForm();
    projectsApi.create.mockRejectedValue(new Error("Select a published template version."));
    fireEvent.click(screen.getByRole("button", { name: /create draft/i }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Select a published template version");
    expect(screen.getByRole("heading", { name: /create draft project/i })).toBeInTheDocument();
  });

  it("uses responsive full-width mobile actions", async () => {
    await openForm();
    expect(screen.getByRole("button", { name: /create draft/i })).toHaveClass("w-full", "sm:w-auto");
    expect(screen.getByRole("button", { name: /cancel/i })).toHaveClass("w-full", "sm:w-auto");
  });
});
