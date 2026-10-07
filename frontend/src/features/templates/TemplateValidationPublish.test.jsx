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
const task = { id:"task-1", code:"T001", title:"Confirm site", sequence_no:1, schedule_classification:"execution", planned_start_day:1, planned_end_day:1, applicability:"mandatory", phase:"Survey", category:"Planning", task_class:null, task_kind:null, evidence_required:false, duration_days:1 };
const gate = { id:"gate-1", code:"E001", approval_name:"Fire NOC", description:null, external_party:"Government Authority", required_by_type:null, required_by_value:null, impact:null, sequence_no:1, mapping_classification:"unmapped", broad_mapping_text:null, requires_configuration:true, affected_tasks:[] };
const page = items => ({ items, pagination:{ page:1, page_size:100, total:items.length, total_pages:items.length ? 1 : 0 }, summary:{ total:items.length } });
const valid = {
  version_id:"draft-1", version_status:"draft", draft_revision:"rev-1", validated_at:"2026-07-28T11:00:00Z", is_valid:true, can_publish:true,
  issues:[], severity_counts:{ errors:0, warnings:0, blocking:0, non_blocking:0 }, entity_counts:{ tasks:1, dependencies:0, gates:1, exact_mappings:0 },
};
const issue = (code, blocking, group, entity_type, entity_id, message) => ({ code, severity:blocking ? "error" : "warning", blocking, group, entity_type, entity_id, path:"x", message, details:{} });
const invalid = {
  ...valid, is_valid:false, can_publish:false,
  issues:[
    issue("task_code_duplicate", true, "tasks", "task", "task-1", "Task code must be unique within the version."),
    issue("dependency_cycle", true, "dependencies", "version", "draft-1", "Dependency graph must remain acyclic."),
    issue("gate_due_date_missing", false, "gates", "gate", "gate-1", "This approval has no due date. Date-based overdue reminders will not apply."),
  ],
  severity_counts:{ errors:2, warnings:1, blocking:2, non_blocking:1 },
};
const warningsOnly = { ...valid, issues:[invalid.issues[2]], severity_counts:{ errors:0, warnings:1, blocking:0, non_blocking:1 } };

function view(props={}) {
  return render(<TemplateDraftEditorEntry summary={props.summary || summary} user={{ role:props.role || "admin" }} onBack={vi.fn()} onPublished={props.onPublished || vi.fn()}/>);
}
async function openReview() {
  await screen.findByTestId("draft-task-T001");
  fireEvent.click(screen.getByRole("button", { name:/review & publish/i }));
  return screen.findByTestId("template-validation-publish");
}

beforeEach(() => {
  vi.clearAllMocks();
  templatesApi.getVersion.mockResolvedValue(summary);
  templatesApi.listTasks.mockResolvedValue(page([task]));
  templatesApi.listDependencies.mockResolvedValue(page([]));
  templatesApi.listGates.mockResolvedValue(page([gate]));
  templatesApi.validateVersion.mockResolvedValue(valid);
  templatesApi.publishVersion.mockResolvedValue({ version_id:"draft-1", template_id:"template-1", version_no:2, status:"published", is_current_published:true, published_at:"2026-07-28T11:05:00Z", published_by:"user-1", content_hash:"abc", previous_current_version_id:"version-1" });
});

describe("review and publish", () => {
  it("checks the draft as soon as Review opens", async () => {
    view(); await openReview();
    await waitFor(() => expect(templatesApi.validateVersion).toHaveBeenCalledWith("draft-1"));
    expect(await screen.findByText("Ready to publish. No problems found.")).toBeInTheDocument();
  });

  it("separates must-fix problems from warnings and explains each in plain words", async () => {
    templatesApi.validateVersion.mockResolvedValue(invalid);
    view(); await openReview();
    const mustFix = await screen.findByRole("region", { name:"Must fix before publishing" });
    expect(within(mustFix).getByText("Two tasks share the same code")).toBeInTheDocument();
    expect(within(mustFix).getByText("T001 · Confirm site")).toBeInTheDocument();
    expect(within(mustFix).getByText("Some tasks wait for each other in a loop")).toBeInTheDocument();
    expect(within(mustFix).getByText(/could ever start/i)).toBeInTheDocument();
    const check = screen.getByRole("region", { name:"Worth checking" });
    expect(within(check).getByText("An approval has no due date")).toBeInTheDocument();
    expect(within(check).getByText("Fire NOC")).toBeInTheDocument();
    expect(screen.queryByText(/acyclic|task_code_duplicate/)).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name:/^publish$/i })).toBeDisabled();
  });

  it("Fix opens the task or approval the problem is about", async () => {
    templatesApi.validateVersion.mockResolvedValue(invalid);
    view(); await openReview();
    const mustFix = await screen.findByRole("region", { name:"Must fix before publishing" });
    fireEvent.click(within(mustFix).getByRole("button", { name:"Fix: Two tasks share the same code" }));
    expect(screen.getByRole("dialog", { name:/edit task/i })).toBeInTheDocument();
    fireEvent.click(within(screen.getByRole("dialog")).getByRole("button", { name:/cancel/i }));
    fireEvent.click(screen.getByRole("button", { name:/review & publish/i }));
    fireEvent.click(within(screen.getByRole("region", { name:"Worth checking" })).getByRole("button", { name:"Fix: An approval has no due date" }));
    expect(screen.getByRole("dialog", { name:/edit prerequisite approval/i })).toBeInTheDocument();
  });

  it("lets warnings through to publishing", async () => {
    templatesApi.validateVersion.mockResolvedValue(warningsOnly);
    view(); await openReview();
    expect(await screen.findByText(/1 thing worth checking/i)).toBeInTheDocument();
    expect(screen.getByRole("button", { name:/^publish$/i })).toBeEnabled();
  });

  it("asks for a change note and publishes the checked revision", async () => {
    const onPublished = vi.fn();
    view({ onPublished }); await openReview();
    await screen.findByText("Ready to publish. No problems found.");
    fireEvent.click(screen.getByRole("button", { name:/^publish$/i }));
    const dialog = screen.getByRole("dialog", { name:/publish this version/i });
    expect(within(dialog).getByText(/existing projects don't change/i)).toBeInTheDocument();
    fireEvent.click(within(dialog).getByRole("button", { name:/^publish$/i }));
    expect(await within(dialog).findByText(/change note is required/i)).toBeInTheDocument();
    fireEvent.change(within(dialog).getByLabelText("Change note"), { target:{ value:" Approved final sequencing " } });
    fireEvent.click(within(dialog).getByRole("button", { name:/^publish$/i }));
    await waitFor(() => expect(templatesApi.publishVersion).toHaveBeenCalledWith("draft-1", { revision_token:"rev-1", change_note:"Approved final sequencing" }));
    expect(onPublished).toHaveBeenCalledWith(expect.objectContaining({ status:"published", previous_current_version_id:"version-1" }));
  });

  it("pre-fills the change note with the draft's own note", async () => {
    templatesApi.getVersion.mockResolvedValue({ ...summary, change_note:"Retail variant." });
    view({ summary:{ ...summary, change_note:"Retail variant." } }); await openReview();
    await screen.findByText("Ready to publish. No problems found.");
    fireEvent.click(screen.getByRole("button", { name:/^publish$/i }));
    const dialog = screen.getByRole("dialog", { name:/publish this version/i });
    expect(within(dialog).getByLabelText("Change note")).toHaveValue("Retail variant.");
    fireEvent.click(within(dialog).getByRole("button", { name:/^publish$/i }));
    await waitFor(() => expect(templatesApi.publishVersion).toHaveBeenCalledWith("draft-1", { revision_token:"rev-1", change_note:"Retail variant." }));
  });

  it("asks for a new check when the draft changes after one", async () => {
    const { rerender } = view(); await openReview();
    await screen.findByText("Ready to publish. No problems found.");
    rerender(<TemplateDraftEditorEntry summary={{...summary, revision_token:"rev-2"}} user={{role:"admin"}} onBack={vi.fn()} onPublished={vi.fn()}/>);
    expect(await screen.findByText("The draft changed since this check")).toBeInTheDocument();
    expect(screen.getByRole("button", { name:/^publish$/i })).toBeDisabled();
  });

  it("keeps controls mobile-friendly and unavailable to roles that cannot edit", async () => {
    view(); await openReview();
    expect(screen.getByRole("button", { name:/check again/i })).toHaveClass("w-full");
    cleanup();
    view({ role:"project_manager" });
    expect(await screen.findByText("Draft authoring is unavailable")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name:/check again/i })).not.toBeInTheDocument();
  });
});
