import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { projectsApi } from "../../api/projectsApi";
import { ProjectDetailModal } from "./components/ProjectDetailModal";

vi.mock("../../api/projectsApi", () => ({
  projectsApi: {
    detail: vi.fn(),
    activity: vi.fn(),
    generateTasks: vi.fn(),
    templateReviewTasks: vi.fn(),
    templateReviewSummary: vi.fn(),
    setStatus: vi.fn(),
    setMembership: vi.fn(),
    remove: vi.fn(),
  },
}));

const project = {
  id: "project-1",
  code: "PRJ-001",
  name: "Khar Commercial Project",
  client_name: "Castrol India",
  site_address: "Khar, Mumbai",
  description: null,
  start_date: "2026-08-01",
  target_handover_date: null,
  template_version_id: "version-1",
  status: "draft",
  memberships: [],
  membership_history: [],
  setup: {
    has_project_manager: true,
    has_site_supervisor: true,
    has_template: true,
    has_target_handover_date: false,
    activation_ready: false,
  },
};

const templates = [{
  version_id: "version-1",
  version_no: 1,
  template_code: "WORKVED-45",
  template_name: "Workved 45-Day Permanent Task Template",
  duration_days: 45,
  status: "published",
  is_current_published: true,
}];

function renderModal() {
  return render(<ProjectDetailModal
    projectId="project-1"
    references={{ project_managers: [], supervisors: [], internal_employees: [] }}
    templates={templates}
    user={{ id: "admin-1", role: "admin" }}
    onClose={vi.fn()}
    onEdit={vi.fn()}
    onChanged={vi.fn().mockResolvedValue(undefined)}
    onDeleted={vi.fn()}
  />);
}

beforeEach(() => {
  vi.clearAllMocks();
  projectsApi.detail.mockResolvedValue(project);
  projectsApi.activity.mockResolvedValue([]);
  projectsApi.templateReviewTasks.mockResolvedValue({ items: [], pagination: { page: 1, page_size: 100, total: 0, total_pages: 0 } });
  projectsApi.templateReviewSummary.mockResolvedValue({ project_id: "project-1", total: 99, included: 99, excluded: 0, pending_review: 99, decided: 0, mandatory: 98, conditional: 1 });
});

describe("Draft project task generation", () => {
  it("confirms, generates once, shows the count, moves to Template Review and keeps Draft status", async () => {
    projectsApi.generateTasks.mockResolvedValue({
      project_id: "project-1",
      status: "draft",
      template_version_id: "version-1",
      generated_task_count: 99,
      created_task_count: 99,
      no_op: false,
    });
    projectsApi.activity
      .mockResolvedValueOnce([])
      .mockResolvedValueOnce([{ id: "audit-1", action: "PROJECT_TASKS_GENERATED", after: { generated_task_count: 99 }, occurred_at: "2026-07-29T10:00:00Z", actor_name: "Admin", reason: "Generated" }]);

    renderModal();
    expect(await screen.findByText("Workved 45-Day Permanent Task Template")).toBeInTheDocument();
    const generate = screen.getByRole("button", { name: /generate tasks/i });
    expect(generate).toBeDisabled();
    fireEvent.click(screen.getByRole("checkbox"));
    fireEvent.click(generate);
    fireEvent.click(generate);

    await waitFor(() => expect(projectsApi.generateTasks).toHaveBeenCalledTimes(1));
    expect(await screen.findByText(/99 template-derived tasks/i)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /template review/i })).toHaveClass("bg-white");
    expect(screen.getByText("draft", { selector: "span" })).toBeInTheDocument();
  });

  it("renders an already-generated state from audit history without calling generation", async () => {
    projectsApi.activity.mockResolvedValue([{ id: "audit-1", action: "PROJECT_TASKS_GENERATED", after: { generated_task_count: 99 }, occurred_at: "2026-07-29T10:00:00Z", actor_name: "Admin", reason: "Generated" }]);
    renderModal();
    expect(await screen.findByText(/99 template-derived tasks/i)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /^generate tasks$/i })).not.toBeInTheDocument();
    expect(projectsApi.generateTasks).not.toHaveBeenCalled();
  });

  it("shows an error and allows a controlled retry", async () => {
    projectsApi.generateTasks
      .mockRejectedValueOnce(new Error("Generation transaction rolled back."))
      .mockResolvedValueOnce({ project_id: "project-1", status: "draft", generated_task_count: 99, created_task_count: 99, no_op: false });
    projectsApi.activity
      .mockResolvedValueOnce([])
      .mockResolvedValueOnce([{ id: "audit-1", action: "PROJECT_TASKS_GENERATED", after: { generated_task_count: 99 }, occurred_at: "2026-07-29T10:00:00Z", actor_name: "Admin", reason: "Generated" }]);

    renderModal();
    await screen.findByText("Workved 45-Day Permanent Task Template");
    fireEvent.click(screen.getByRole("checkbox"));
    fireEvent.click(screen.getByRole("button", { name: /generate tasks/i }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Generation transaction rolled back");
    fireEvent.click(screen.getByRole("button", { name: /retry generation/i }));
    await waitFor(() => expect(projectsApi.generateTasks).toHaveBeenCalledTimes(2));
    expect(await screen.findByText(/99 template-derived tasks/i)).toBeInTheDocument();
  });

  it("uses a full-width mobile action", async () => {
    renderModal();
    await screen.findByText("Workved 45-Day Permanent Task Template");
    expect(screen.getByRole("button", { name: /generate tasks/i })).toHaveClass("w-full", "sm:w-auto");
  });
});
