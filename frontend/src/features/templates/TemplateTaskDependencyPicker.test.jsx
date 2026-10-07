import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { templatesApi } from "../../api/templatesApi";
import { TemplateDraftEditorEntry } from "./components/TemplateDraftEditorEntry";

vi.mock("../../api/templatesApi", () => ({ templatesApi: {
  getVersion: vi.fn(), listTasks: vi.fn(), listDependencies: vi.fn(), listGates: vi.fn(),
  createTask: vi.fn(), updateTask: vi.fn(), createDependency: vi.fn(), deleteDependency: vi.fn(),
} }));

const summary = { version_id: "draft-1", template_code: "TEST-45", template_name: "Test schedule", version_no: 2, status: "draft", duration_days: 45, updated_at: "2026-07-28T10:00:00Z", revision_token: "rev-1" };
const task = (id, code, title, start) => ({ id, template_version_id: "draft-1", code, sequence_no: Number(code.slice(1)), title, description: null, schedule_classification: "execution", planned_start_day: start, planned_end_day: start, phase: "Civil", category: "Civil", applicability: "mandatory", task_class: null, task_kind: null, evidence_required: false, duration_days: 1, validation_state: "valid", validation_issues: [] });
const tasks = [task("task-1", "T001", "Survey", 1), task("task-2", "T002", "Screeding", 2), task("task-3", "T003", "Floor levelling", 3)];
const ref = t => ({ id: t.id, code: t.code, title: t.title });
const dependency = (id, pred, succ, overrides = {}) => ({ id, sequence_no: 1, dependency_type: "finish_to_start", blocking: true, rule_text: "x", predecessor: ref(pred), successor: ref(succ), validation_state: "valid", validation_issues: [], ...overrides });
const page = items => ({ items, pagination: { page: 1, page_size: 100, total: items.length, total_pages: items.length ? 1 : 0 } });

function view() { return render(<TemplateDraftEditorEntry summary={summary} user={{ role: "admin" }} onBack={vi.fn()}/>); }
async function openTask(code) {
  await screen.findByTestId(`draft-task-${code}`);
  fireEvent.click(screen.getAllByRole("button", { name: `Edit ${code}` })[0]);
  return screen.getByRole("dialog", { name: /edit task/i });
}
const waitsFor = dialog => within(dialog).getByRole("group", { name: "Can't start until" });

beforeEach(() => {
  vi.clearAllMocks();
  templatesApi.getVersion.mockResolvedValue(summary);
  templatesApi.listTasks.mockResolvedValue(page(tasks));
  templatesApi.listDependencies.mockResolvedValue(page([dependency("dep-1", tasks[0], tasks[1])]));
  templatesApi.listGates.mockResolvedValue(page([]));
  templatesApi.updateTask.mockResolvedValue({ task: tasks[2], revision_token: "rev-2" });
  templatesApi.createDependency.mockResolvedValue({ dependency: {}, revision_token: "rev-3" });
  templatesApi.deleteDependency.mockResolvedValue({ revision_token: "rev-3" });
});

describe("Can't start until", () => {
  it("shows the tasks a task waits for, in plain words", async () => {
    view();
    const dialog = await openTask("T002");
    expect(within(waitsFor(dialog)).getByText("T001 · Survey")).toBeInTheDocument();
    expect(within(dialog).queryByText(/predecessor|successor|finish-to-start/i)).not.toBeInTheDocument();
  });

  it("adds a finish-first link without re-saving an unchanged task", async () => {
    view();
    const dialog = await openTask("T003");
    fireEvent.change(within(dialog).getByLabelText("Add a task it waits for"), { target: { value: "task-2" } });
    fireEvent.click(within(dialog).getByRole("button", { name: /save task/i }));
    await waitFor(() => expect(templatesApi.createDependency).toHaveBeenCalledWith("draft-1", {
      predecessor_task_id: "task-2", successor_task_id: "task-3", dependency_type: "finish_to_start", blocking: true,
      rule_text: "T003 can't start until T002 is finished.", sequence_no: 2, revision_token: "rev-1",
    }));
    expect(templatesApi.updateTask).not.toHaveBeenCalled();
  });

  it("removes a link and chains the revision after a task edit", async () => {
    view();
    const dialog = await openTask("T002");
    fireEvent.change(within(dialog).getByLabelText("Task name"), { target: { value: "Screeding works" } });
    fireEvent.click(within(waitsFor(dialog)).getByRole("button", { name: "Remove T001" }));
    fireEvent.click(within(dialog).getByRole("button", { name: /save task/i }));
    await waitFor(() => expect(templatesApi.deleteDependency).toHaveBeenCalledWith("draft-1", "dep-1", "rev-2"));
    expect(templatesApi.updateTask).toHaveBeenCalledWith("draft-1", "task-2", expect.objectContaining({ title: "Screeding works", revision_token: "rev-1" }));
  });

  it("does not offer a task that would make the two wait for each other", async () => {
    view();
    const dialog = await openTask("T001");
    const options = [...within(dialog).getByLabelText("Add a task it waits for").options].map(option => option.value);
    expect(options).toContain("task-3");
    expect(options).not.toContain("task-2");
    expect(options).not.toContain("task-1");
  });

  it("links a new task once it exists", async () => {
    templatesApi.createTask.mockResolvedValue({ task: { ...tasks[2], id: "task-4", code: "T004" }, revision_token: "rev-2" });
    view();
    await screen.findByTestId("draft-task-T001");
    fireEvent.click(screen.getByRole("button", { name: /add task/i }));
    const dialog = screen.getByRole("dialog", { name: /add task/i });
    fireEvent.change(within(dialog).getByLabelText("Task name"), { target: { value: "Tiling" } });
    fireEvent.change(within(dialog).getByLabelText("Starts on day"), { target: { value: "5" } });
    fireEvent.change(within(dialog).getByLabelText("Add a task it waits for"), { target: { value: "task-3" } });
    fireEvent.click(within(dialog).getByRole("button", { name: /add task/i }));
    await waitFor(() => expect(templatesApi.createDependency).toHaveBeenCalledWith("draft-1", expect.objectContaining({
      predecessor_task_id: "task-3", successor_task_id: "task-4", rule_text: "T004 can't start until T003 is finished.", revision_token: "rev-2",
    })));
  });

  it("keeps advanced links read-only in the task dialog", async () => {
    templatesApi.listDependencies.mockResolvedValue(page([dependency("dep-2", tasks[0], tasks[1], { dependency_type: "start_to_start" })]));
    view();
    const dialog = await openTask("T002");
    expect(within(dialog).getByText(/T001 · Survey has started/)).toBeInTheDocument();
    expect(within(dialog).queryByRole("button", { name: "Remove T001" })).not.toBeInTheDocument();
  });

  it("reports links that failed after the task itself was saved", async () => {
    templatesApi.createDependency.mockRejectedValue({ status: 409, message: "Conflict", details: { detail: { code: "template_dependency_cycle", message: "cycle" } } });
    view();
    const dialog = await openTask("T003");
    fireEvent.change(within(dialog).getByLabelText("Task name"), { target: { value: "Levelling" } });
    fireEvent.change(within(dialog).getByLabelText("Add a task it waits for"), { target: { value: "task-1" } });
    fireEvent.click(within(dialog).getByRole("button", { name: /save task/i }));
    expect(await screen.findByText(/task was saved, but its "can't start until" links were not all saved/i)).toBeInTheDocument();
    expect(screen.getByText(/wait for each other in a loop/i)).toBeInTheDocument();
  });
});
