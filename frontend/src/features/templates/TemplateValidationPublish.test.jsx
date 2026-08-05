import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { templatesApi } from "../../api/templatesApi";
import { TemplateDraftEditorEntry } from "./components/TemplateDraftEditorEntry";

vi.mock("../../api/templatesApi", () => ({ templatesApi: {
  getVersion: vi.fn(), listTasks: vi.fn(), listDependencies: vi.fn(), listGates: vi.fn(),
  validateVersion: vi.fn(), publishVersion: vi.fn(),
  createTask: vi.fn(), updateTask: vi.fn(), deleteTask: vi.fn(), reorderTasks: vi.fn(),
  createDependency: vi.fn(), updateDependency: vi.fn(), deleteDependency: vi.fn(),
  createGate: vi.fn(), updateGate: vi.fn(), configureGateMappings: vi.fn(), deleteGate: vi.fn(),
}}));

const summary = { version_id:"draft-1", template_code:"TEST", template_name:"Test Template", version_no:2, status:"draft", duration_days:45, updated_at:"2026-07-28T10:00:00Z", revision_token:"rev-1" };
const task = { id:"task-1", code:"T001", title:"Confirm site", sequence_no:1, applicability:"mandatory", phase:"Pre-Activation", category:"Planning", is_pre_activation:true };
const page = items => ({ items, pagination:{ page:1, page_size:100, total:items.length, total_pages:items.length ? 1 : 0 }, summary:{ total:items.length } });
const valid = {
  version_id:"draft-1", version_status:"draft", draft_revision:"rev-1", validated_at:"2026-07-28T11:00:00Z", is_valid:true, can_publish:true,
  issues:[], severity_counts:{ errors:0, warnings:0, blocking:0, non_blocking:0 }, entity_counts:{ tasks:1, dependencies:0, gates:0, exact_mappings:0 },
};
const invalid = {
  ...valid, is_valid:false, can_publish:false,
  issues:[
    { code:"task_code_duplicate", severity:"error", blocking:true, group:"tasks", entity_type:"task", entity_id:"task-1", path:"tasks.code", message:"Task code is duplicated.", details:{} },
    { code:"dependency_cycle", severity:"error", blocking:true, group:"dependencies", entity_type:"dependency", entity_id:null, path:"dependencies", message:"Dependency graph contains a cycle.", details:{} },
    { code:"gate_configuration_required", severity:"warning", blocking:false, group:"gates", entity_type:"gate", entity_id:"gate-1", path:"gates.mapping", message:"Gate requires configuration.", details:{} },
  ],
  severity_counts:{ errors:2, warnings:1, blocking:2, non_blocking:1 }, entity_counts:{ tasks:1, dependencies:1, gates:1, exact_mappings:0 },
};

function view(props={}) {
  return render(<TemplateDraftEditorEntry summary={props.summary || summary} user={{ role:props.role || "super_admin" }} onBack={vi.fn()} onPublished={props.onPublished || vi.fn()}/>);
}
async function openValidation() {
  await screen.findByTestId("draft-task-T001");
  fireEvent.click(screen.getByRole("button", { name:/validate & publish/i }));
  return screen.findByTestId("template-validation-publish");
}

beforeEach(() => {
  vi.clearAllMocks();
  templatesApi.getVersion.mockResolvedValue(summary);
  templatesApi.listTasks.mockResolvedValue(page([task]));
  templatesApi.listDependencies.mockResolvedValue(page([]));
  templatesApi.listGates.mockResolvedValue(page([]));
  templatesApi.validateVersion.mockResolvedValue(valid);
  templatesApi.publishVersion.mockResolvedValue({ version_id:"draft-1", template_id:"template-1", version_no:2, status:"published", is_current_published:true, published_at:"2026-07-28T11:05:00Z", published_by:"user-1", content_hash:"abc", previous_current_version_id:"version-1" });
});

describe("template validation and publication", () => {
  it("renders validation results and keeps publish disabled with blocking errors", async () => {
    templatesApi.validateVersion.mockResolvedValue(invalid);
    view(); await openValidation();
    fireEvent.click(screen.getByRole("button", { name:/validate draft/i }));
    expect(await screen.findByText("Validation has blocking issues")).toBeInTheDocument();
    expect(screen.getByText("Task code is duplicated.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name:/publish version/i })).toBeDisabled();
  });

  it("navigates issues to tasks, dependencies and external gates", async () => {
    templatesApi.validateVersion.mockResolvedValue(invalid);
    view(); await openValidation();
    fireEvent.click(screen.getByRole("button", { name:/validate draft/i }));
    await screen.findByText("Dependency graph contains a cycle.");
    fireEvent.click(screen.getByRole("button", { name:/open dependencies issues/i }));
    expect(screen.getByText("Dependencies · Draft authoring")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name:/validate & publish/i }));
    fireEvent.click(screen.getByRole("button", { name:/open external gates issues/i }));
    expect(screen.getByText("External gates · Draft authoring")).toBeInTheDocument();
  });

  it("requires confirmation note and publishes the validated revision", async () => {
    const onPublished = vi.fn();
    view({ onPublished }); await openValidation();
    fireEvent.click(screen.getByRole("button", { name:/validate draft/i }));
    expect(await screen.findByText("Validation passed")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name:/publish version/i }));
    const dialog = screen.getByRole("dialog", { name:/publish template version/i });
    expect(within(dialog).getByText(/become immutable/i)).toBeInTheDocument();
    fireEvent.click(within(dialog).getByRole("button", { name:/publish immutable version/i }));
    expect(await within(dialog).findByText(/change note is required/i)).toBeInTheDocument();
    fireEvent.change(within(dialog).getByLabelText("Publication change note"), { target:{ value:" Approved final sequencing " } });
    fireEvent.click(within(dialog).getByRole("button", { name:/publish immutable version/i }));
    await waitFor(() => expect(templatesApi.publishVersion).toHaveBeenCalledWith("draft-1", { revision_token:"rev-1", change_note:"Approved final sequencing" }));
    expect(onPublished).toHaveBeenCalledWith(expect.objectContaining({ status:"published", previous_current_version_id:"version-1" }));
  });

  it("marks validation stale when the draft revision changes", async () => {
    const { rerender } = view(); await openValidation();
    fireEvent.click(screen.getByRole("button", { name:/validate draft/i }));
    await screen.findByText("Validation passed");
    rerender(<TemplateDraftEditorEntry summary={{...summary, revision_token:"rev-2"}} user={{role:"super_admin"}} onBack={vi.fn()} onPublished={vi.fn()}/>);
    expect(await screen.findByText("Validation result is stale")).toBeInTheDocument();
    expect(screen.getByRole("button", { name:/publish version/i })).toBeDisabled();
  });

  it("keeps controls mobile-friendly and unavailable to non-Super-Admin roles", async () => {
    view(); await openValidation();
    expect(screen.getByRole("button", { name:/validate draft/i })).toHaveClass("w-full");
    cleanup();
    view({ role:"admin" });
    expect(await screen.findByText("Draft authoring is unavailable")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name:/validate draft/i })).not.toBeInTheDocument();
  });
});
