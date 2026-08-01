import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { templatesApi } from "../../api/templatesApi";
import { TemplatesPage } from "./TemplatesPage";

vi.mock("../../api/templatesApi", () => ({
  templatesApi: {
    list: vi.fn(),
    create: vi.fn(),
    cloneVersion: vi.fn(),
    getVersion: vi.fn(),
    listTasks: vi.fn(),
    listDependencies: vi.fn(),
    listGates: vi.fn(),
  },
}));

const published = {
  template_id: "template-1",
  template_code: "WORKVED-45",
  template_name: "Workved 45-Day Interior Delivery",
  template_description: "Approved schedule",
  version_id: "version-published",
  version_no: 1,
  status: "published",
  is_current_published: true,
  duration_days: 45,
  task_count: 99,
  dependency_count: 38,
  gate_count: 32,
  created_at: "2026-07-24T10:00:00Z",
  published_at: "2026-07-25T10:00:00Z",
};

const draft = {
  ...published,
  template_id: "template-new",
  template_code: "WORKVED-60",
  template_name: "New controlled template",
  template_description: "New scope",
  version_id: "version-draft",
  version_no: 1,
  status: "draft",
  is_current_published: false,
  duration_days: 60,
  task_count: 0,
  dependency_count: 0,
  gate_count: 0,
  published_at: null,
};

const page = items => ({
  items,
  pagination: { page: 1, page_size: 20, total: items.length, total_pages: items.length ? 1 : 0 },
});

function renderPage(role = "super_admin") {
  return render(<TemplatesPage user={{ id: "user-1", role }} debounceMs={0}/>);
}

async function openPublishedDetails() {
  const card = await screen.findByTestId("template-card-version-published");
  fireEvent.click(within(card).getByRole("button", { name: /view details/i }));
  await screen.findByText("Workved 45-Day Interior Delivery");
}

beforeEach(() => {
  vi.clearAllMocks();
  templatesApi.list.mockResolvedValue(page([published]));
  templatesApi.getVersion.mockImplementation(versionId => Promise.resolve(versionId === draft.version_id ? draft : published));
  templatesApi.listTasks.mockResolvedValue({ items: [], pagination: { page: 1, page_size: 20, total: 0, total_pages: 0 } });
  templatesApi.listDependencies.mockResolvedValue({ items: [], pagination: { page: 1, page_size: 100, total: 0, total_pages: 0 }, summary: { total: 0, finish_to_start: 0, start_to_start: 0, blocking: 0, validation_issues: 0 } });
  templatesApi.listGates.mockResolvedValue({ items: [], pagination: { page: 1, page_size: 100, total: 0, total_pages: 0 } });
});

describe("Phase 2 template authoring entry", () => {
  it("shows Create Template only to Super Admin", async () => {
    const superAdmin = renderPage("super_admin");
    expect(await screen.findByRole("button", { name: /create template/i })).toBeInTheDocument();
    superAdmin.unmount();

    for (const role of ["admin", "project_manager", "supervisor", "internal_employee"]) {
      const view = renderPage(role);
      await screen.findByText("Template library");
      expect(screen.queryByRole("button", { name: /create template/i })).not.toBeInTheDocument();
      view.unmount();
    }
  });

  it("validates create fields and renders duplicate-code conflicts", async () => {
    renderPage();
    fireEvent.click(await screen.findByRole("button", { name: /create template/i }));
    const dialog = screen.getByRole("dialog", { name: /create template/i });
    fireEvent.click(within(dialog).getByRole("button", { name: /create template/i }));
    expect(await within(dialog).findByText("Template code is required.")).toBeInTheDocument();
    expect(within(dialog).getByText("Template name is required.")).toBeInTheDocument();

    templatesApi.create.mockRejectedValue({
      status: 409,
      message: { code: "template_code_exists" },
      details: { detail: { code: "template_code_exists", message: "Template code WORKVED-45 already exists." } },
    });
    fireEvent.change(within(dialog).getByLabelText("Template code"), { target: { value: "WORKVED-45" } });
    fireEvent.change(within(dialog).getByLabelText("Template name"), { target: { value: "Duplicate" } });
    fireEvent.click(within(dialog).getByRole("button", { name: /create template/i }));
    expect(await within(dialog).findByText("Template code WORKVED-45 already exists.")).toBeInTheDocument();
  });

  it("creates a template and opens its new draft details", async () => {
    templatesApi.create.mockResolvedValue({
      template_id: draft.template_id,
      template_code: draft.template_code,
      template_name: draft.template_name,
      version_id: draft.version_id,
      version_no: 1,
      status: "draft",
      duration_days: 60,
      task_count: 0,
      dependency_count: 0,
      gate_count: 0,
      exact_mapping_count: 0,
    });
    const { container } = renderPage();
    fireEvent.click(await screen.findByRole("button", { name: /create template/i }));
    const dialog = screen.getByRole("dialog", { name: /create template/i });
    fireEvent.change(within(dialog).getByLabelText("Template code"), { target: { value: " WORKVED-60 " } });
    fireEvent.change(within(dialog).getByLabelText("Template name"), { target: { value: " New controlled template " } });
    fireEvent.change(within(dialog).getByLabelText("Description"), { target: { value: " New scope " } });
    fireEvent.change(within(dialog).getByLabelText("Duration (days)"), { target: { value: "60" } });
    fireEvent.change(within(dialog).getByLabelText("Initial change note"), { target: { value: " Initial authoring " } });
    fireEvent.click(within(dialog).getByRole("button", { name: /create template/i }));

    await waitFor(() => expect(templatesApi.create).toHaveBeenCalledWith({
      code: "WORKVED-60",
      name: "New controlled template",
      description: "New scope",
      duration_days: 60,
      change_note: "Initial authoring",
    }));
    expect(await screen.findByText("New controlled template")).toBeInTheDocument();
    expect(container.querySelector("[data-template-view]")).toHaveAttribute("data-selected-version-id", "version-draft");
    expect(screen.getByRole("button", { name: /open draft editor/i })).toBeInTheDocument();
  });

  it("shows clone only to Super Admin and keeps a published source view-only", async () => {
    renderPage("super_admin");
    await openPublishedDetails();
    expect(screen.getByRole("button", { name: /clone as draft/i })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /open draft editor/i })).not.toBeInTheDocument();
    expect(screen.getByText("Published version is view-only")).toBeInTheDocument();
  });

  it("requires a clone change note, explains isolation, and opens the cloned draft", async () => {
    templatesApi.cloneVersion.mockResolvedValue({
      source_version_id: published.version_id,
      template_id: draft.template_id,
      template_code: published.template_code,
      template_name: published.template_name,
      version_id: draft.version_id,
      version_no: 2,
      status: "draft",
      duration_days: 45,
      task_count: 99,
      dependency_count: 38,
      gate_count: 32,
      exact_mapping_count: 12,
    });
    templatesApi.getVersion.mockImplementation(versionId => Promise.resolve(versionId === draft.version_id
      ? { ...draft, template_id: published.template_id, template_code: published.template_code, template_name: published.template_name, version_no: 2, duration_days: 45, task_count: 99, dependency_count: 38, gate_count: 32 }
      : published));

    renderPage();
    await openPublishedDetails();
    fireEvent.click(screen.getByRole("button", { name: /clone as draft/i }));
    const dialog = screen.getByRole("dialog", { name: /clone version as draft/i });
    expect(within(dialog).getByText("Source remains unchanged")).toBeInTheDocument();
    expect(within(dialog).getByText("Separate draft")).toBeInTheDocument();
    fireEvent.click(within(dialog).getByRole("button", { name: /clone as draft/i }));
    expect(await within(dialog).findByText("A change note is required for the new draft.")).toBeInTheDocument();

    fireEvent.change(within(dialog).getByLabelText("Change note"), { target: { value: " Rework sequencing " } });
    fireEvent.click(within(dialog).getByRole("button", { name: /clone as draft/i }));
    await waitFor(() => expect(templatesApi.cloneVersion).toHaveBeenCalledWith("version-published", { change_note: "Rework sequencing" }));
    expect(await screen.findByRole("button", { name: /open draft editor/i })).toBeInTheDocument();
  });

  it("opens the draft editor entry without exposing mutation controls on published versions", async () => {
    templatesApi.list.mockResolvedValue(page([draft]));
    templatesApi.getVersion.mockResolvedValue(draft);
    renderPage();
    const card = await screen.findByTestId("template-card-version-draft");
    fireEvent.click(within(card).getByRole("button", { name: /view details/i }));
    fireEvent.click(await screen.findByRole("button", { name: /open draft editor/i }));
    expect(await screen.findByTestId("template-draft-editor")).toBeInTheDocument();
    expect(screen.getByText("Draft task authoring")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /back to draft details/i })).toBeInTheDocument();
  });

  it("clears draft editor state when the active role loses authoring access", async () => {
    templatesApi.list.mockResolvedValue(page([draft]));
    templatesApi.getVersion.mockResolvedValue(draft);
    const view = render(<TemplatesPage user={{ id: "user-1", role: "super_admin" }} debounceMs={0}/>);
    const card = await screen.findByTestId("template-card-version-draft");
    fireEvent.click(within(card).getByRole("button", { name: /view details/i }));
    fireEvent.click(await screen.findByRole("button", { name: /open draft editor/i }));
    await screen.findByTestId("template-draft-editor");

    view.rerender(<TemplatesPage user={{ id: "user-1", role: "admin" }} debounceMs={0}/>);
    await waitFor(() => expect(view.container.querySelector("[data-template-view]")).toHaveAttribute("data-template-view", "list"));
    expect(view.container.querySelector("[data-template-view]")).toHaveAttribute("data-selected-version-id", "");
  });

  it.each(["admin", "project_manager"])("keeps %s details fully read-only", async role => {
    renderPage(role);
    await openPublishedDetails();
    expect(screen.queryByRole("button", { name: /clone as draft/i })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /open draft editor/i })).not.toBeInTheDocument();
    expect(screen.getByText("Published version is view-only")).toBeInTheDocument();
  });

  it("keeps create on the form when the mutation response has no draft version ID", async () => {
    templatesApi.create.mockResolvedValue({
      template_id: "template-new",
      version_id: null,
      status: "draft",
    });
    const { container } = renderPage();
    fireEvent.click(await screen.findByRole("button", { name: /create template/i }));
    const dialog = screen.getByRole("dialog", { name: /create template/i });
    fireEvent.change(within(dialog).getByLabelText("Template code"), { target: { value: "SAFE-01" } });
    fireEvent.change(within(dialog).getByLabelText("Template name"), { target: { value: "Safe template" } });
    fireEvent.click(within(dialog).getByRole("button", { name: /create template/i }));

    expect(await within(dialog).findByText("The server did not confirm the new draft. Nothing was opened.")).toBeInTheDocument();
    expect(container.querySelector("[data-template-view]")).toHaveAttribute("data-template-view", "list");
    expect(templatesApi.getVersion).not.toHaveBeenCalled();
  });

  it("rejects a clone response that reuses the published source version ID", async () => {
    templatesApi.cloneVersion.mockResolvedValue({
      source_version_id: published.version_id,
      template_id: published.template_id,
      version_id: published.version_id,
      version_no: 2,
      status: "draft",
    });
    renderPage();
    await openPublishedDetails();
    fireEvent.click(screen.getByRole("button", { name: /clone as draft/i }));
    const dialog = screen.getByRole("dialog", { name: /clone version as draft/i });
    fireEvent.change(within(dialog).getByLabelText("Change note"), { target: { value: "Separate revision" } });
    fireEvent.click(within(dialog).getByRole("button", { name: /clone as draft/i }));

    expect(await within(dialog).findByText("The server did not return a separate cloned draft. The source remains unchanged.")).toBeInTheDocument();
    expect(screen.getByText("Published version is view-only")).toBeInTheDocument();
    expect(templatesApi.getVersion).toHaveBeenCalledTimes(1);
    expect(templatesApi.getVersion).toHaveBeenCalledWith(published.version_id, expect.any(Object));
  });

  it("locks an in-flight create request against rapid duplicate submission", async () => {
    let resolveCreate;
    templatesApi.create.mockReturnValue(new Promise(resolve => { resolveCreate = resolve; }));
    renderPage();
    fireEvent.click(await screen.findByRole("button", { name: /create template/i }));
    const dialog = screen.getByRole("dialog", { name: /create template/i });
    fireEvent.change(within(dialog).getByLabelText("Template code"), { target: { value: "LOCK-01" } });
    fireEvent.change(within(dialog).getByLabelText("Template name"), { target: { value: "Locked request" } });
    const submit = within(dialog).getByRole("button", { name: /create template/i });
    fireEvent.click(submit);
    fireEvent.click(submit);

    expect(templatesApi.create).toHaveBeenCalledTimes(1);
    resolveCreate({
      template_id: draft.template_id,
      version_id: draft.version_id,
      status: "draft",
    });
    expect(await screen.findByText("New controlled template")).toBeInTheDocument();
  });

  it("locks an in-flight clone request and opens only the returned cloned draft", async () => {
    let resolveClone;
    templatesApi.cloneVersion.mockReturnValue(new Promise(resolve => { resolveClone = resolve; }));
    templatesApi.getVersion.mockImplementation(versionId => Promise.resolve(versionId === draft.version_id
      ? { ...draft, template_id: published.template_id, template_code: published.template_code, template_name: published.template_name, version_no: 2, duration_days: 45, task_count: 99, dependency_count: 38, gate_count: 32 }
      : published));

    const { container } = renderPage();
    await openPublishedDetails();
    fireEvent.click(screen.getByRole("button", { name: /clone as draft/i }));
    const dialog = screen.getByRole("dialog", { name: /clone version as draft/i });
    fireEvent.change(within(dialog).getByLabelText("Change note"), { target: { value: "Locked clone" } });
    const submit = within(dialog).getByRole("button", { name: /clone as draft/i });
    fireEvent.click(submit);
    fireEvent.click(submit);

    expect(templatesApi.cloneVersion).toHaveBeenCalledTimes(1);
    resolveClone({
      source_version_id: published.version_id,
      template_id: published.template_id,
      version_id: draft.version_id,
      version_no: 2,
      status: "draft",
    });
    expect(await screen.findByRole("button", { name: /open draft editor/i })).toBeInTheDocument();
    expect(container.querySelector("[data-template-view]")).toHaveAttribute("data-selected-version-id", draft.version_id);
  });

  it("clears the selected version when returning to the template list", async () => {
    const { container } = renderPage();
    await openPublishedDetails();
    expect(container.querySelector("[data-template-view]")).toHaveAttribute("data-selected-version-id", published.version_id);
    fireEvent.click(screen.getByRole("button", { name: /back to templates/i }));
    expect(container.querySelector("[data-template-view]")).toHaveAttribute("data-template-view", "list");
    expect(container.querySelector("[data-template-view]")).toHaveAttribute("data-selected-version-id", "");
  });
});