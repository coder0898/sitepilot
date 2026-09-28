import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { projectsApi } from "../../api/projectsApi";
import { ProjectTaskClassification } from "./components/ProjectTaskClassification";

vi.mock("../../api/projectsApi", () => ({ projectsApi: { taskClassification: vi.fn(), updateTaskClassification: vi.fn() } }));

const item = (id, code, overrides = {}) => ({
  id, code, sequence: 1, title: `Task ${code}`, phase: "Execution", task_kind: null,
  template_task_class: "class_a", task_class: "class_a", classifiable: true, ...overrides,
});
const listing = (overrides = {}) => ({
  project_id: "p1",
  editable: true,
  items: [
    item("t1", "T001"),
    item("t2", "T002", { template_task_class: null, task_class: null }),
    item("t3", "T003", { task_kind: "approval_gate", template_task_class: null, task_class: null, classifiable: false }),
    item("t4", "T004", { task_kind: "milestone", template_task_class: null, task_class: null, classifiable: false }),
  ],
  ...overrides,
});

beforeEach(() => {
  vi.clearAllMocks();
  projectsApi.taskClassification.mockResolvedValue(listing());
  projectsApi.updateTaskClassification.mockImplementation(async () => listing());
});

describe("ProjectTaskClassification", () => {
  it("defaults each work task to its template class and shows gates read-only", async () => {
    render(<ProjectTaskClassification projectId="p1"/>);
    expect(await screen.findByLabelText("Classification for T001")).toHaveValue("class_a");
    // An unclassified template task shows as Standard.
    expect(screen.getByLabelText("Classification for T002")).toHaveValue("standard");
    // Approval gates and milestones never get a Standard/Class A selector.
    expect(screen.queryByLabelText("Classification for T003")).not.toBeInTheDocument();
    expect(screen.queryByLabelText("Classification for T004")).not.toBeInTheDocument();
    expect(screen.getAllByText("Approval Gate").length).toBeGreaterThan(0);
    expect(screen.getByText("1 Class A · 1 Standard")).toBeInTheDocument();
  });

  it("saves only the overridden tasks", async () => {
    render(<ProjectTaskClassification projectId="p1"/>);
    const select = await screen.findByLabelText("Classification for T001");
    expect(screen.getByRole("button", { name: /Save classification/ })).toBeDisabled();
    fireEvent.change(select, { target: { value: "standard" } });
    fireEvent.click(screen.getByRole("button", { name: /Save classification \(1\)/ }));
    await waitFor(() => expect(projectsApi.updateTaskClassification).toHaveBeenCalledWith("p1", [{ task_id: "t1", task_class: "standard" }]));
  });

  it("bulk controls set every work task and leave gates alone", async () => {
    render(<ProjectTaskClassification projectId="p1"/>);
    await screen.findByLabelText("Classification for T001");
    fireEvent.click(screen.getByRole("button", { name: "Set all Class A" }));
    fireEvent.click(screen.getByRole("button", { name: /Save classification \(1\)/ }));
    await waitFor(() => expect(projectsApi.updateTaskClassification).toHaveBeenCalledWith("p1", [{ task_id: "t2", task_class: "class_a" }]));
    fireEvent.click(screen.getByRole("button", { name: "Set all Standard" }));
    expect(screen.getByLabelText("Classification for T001")).toHaveValue("standard");
    expect(screen.getByLabelText("Classification for T002")).toHaveValue("standard");
  });

  it("is read-only once the project is no longer Draft", async () => {
    projectsApi.taskClassification.mockResolvedValue(listing({ editable: false }));
    render(<ProjectTaskClassification projectId="p1"/>);
    expect(await screen.findByLabelText("Classification for T001")).toBeDisabled();
    expect(screen.queryByRole("button", { name: "Set all Class A" })).not.toBeInTheDocument();
  });
});
