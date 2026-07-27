import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { useState } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { templatesApi } from "../../api/templatesApi";
import { TemplateDetails } from "./TemplateDetails";

vi.mock("../../api/templatesApi", () => ({
  templatesApi: { getVersion: vi.fn(), listTasks: vi.fn(), listDependencies: vi.fn(), listGates: vi.fn(), list: vi.fn() },
}));

const summary = {
  template_id: "template-1",
  template_code: "WORKVED-45",
  template_name: "Workved 45-Day Interior Delivery",
  template_description: "Approved project schedule",
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

function taskRef(code, title, phase, day) {
  return { id: `id-${code}`, code, title, phase, day };
}

function dependency(id, sequence, overrides = {}) {
  return {
    id,
    sequence_no: sequence,
    dependency_type: sequence % 2 ? "finish_to_start" : "start_to_start",
    blocking: sequence !== 2,
    rule_text: `Relationship rule ${sequence}`,
    predecessor: taskRef(sequence === 1 ? "T001" : "T008", sequence === 1 ? "Site mobilisation approval" : "Site marking", sequence === 1 ? "Pre-Activation" : "Site Setup", sequence === 1 ? null : 1),
    successor: taskRef(sequence === 1 ? "T008" : "T009", sequence === 1 ? "Site marking" : "Material inward", "Site Setup", 1),
    validation_state: "valid",
    validation_issues: [],
    ...overrides,
  };
}

const dependencies = [dependency("dep-1", 1), dependency("dep-2", 2)];
const approvedSummary = {
  total: 38,
  finish_to_start: 36,
  start_to_start: 2,
  blocking: 38,
  validation_issues: 0,
};

const dependencyResponse = (items = dependencies, total = 38, summary = approvedSummary) => ({
  items,
  pagination: { page: 1, page_size: 100, total, total_pages: total ? 1 : 0 },
  summary,
});

const taskResponse = {
  items: [{
    id: "id-T001", code: "T001", sequence_no: 1, title: "Site mobilisation approval",
    description: "Approval", schedule_classification: "pre_activation", planned_start_day: null,
    planned_end_day: null, phase: "Pre-Activation", category: "Approval", applicability: "mandatory",
    task_class: "control", task_kind: "approval", evidence_required: false, duration_days: 1,
    validation_state: "valid", validation_issues: [],
  }],
  pagination: { page: 1, page_size: 20, total: 1, total_pages: 1 },
};

function Harness({ role = "admin", initialTab = "tasks" }) {
  const [tab, setTab] = useState(initialTab);
  return <TemplateDetails versionId="version-published" user={{ role }} onBack={vi.fn()} activeTemplateTab={tab} onTabChange={setTab} debounceMs={0}/>;
}

beforeEach(() => {
  vi.clearAllMocks();
  templatesApi.getVersion.mockResolvedValue(summary);
  templatesApi.listTasks.mockResolvedValue(taskResponse);
  templatesApi.listDependencies.mockResolvedValue(dependencyResponse());
});

describe("Template dependency details", () => {
  it("renders 38 total with desktop columns, both task summaries, labels, and mobile cards", async () => {
    render(<Harness initialTab="dependencies"/>);
    expect(await screen.findByText("Task relationships", {}, { timeout: 3000 })).toBeInTheDocument();
    const metrics = screen.getByLabelText("Dependency summary");
    expect(within(metrics).getAllByText("38")).toHaveLength(2);
    expect(within(metrics).getByText("36")).toBeInTheDocument();
    expect(within(metrics).getByText("2")).toBeInTheDocument();
    expect(metrics).toHaveTextContent("Finish-to-Start");
    expect(metrics).toHaveTextContent("Start-to-Start");
    expect(metrics).toHaveTextContent("Blocking");
    expect(metrics).toHaveTextContent("Validation issues");
    expect(screen.getByText("Predecessor")).toBeInTheDocument();
    expect(screen.getByText("Successor")).toBeInTheDocument();
    expect(screen.getAllByText("T001").length).toBeGreaterThan(0);
    expect(screen.getAllByText("T008").length).toBeGreaterThan(0);
    expect(screen.getByTestId("dependency-row-dep-1")).toBeInTheDocument();
    expect(screen.getByTestId("dependency-card-dep-1")).toHaveTextContent("Finish-to-Start");
    expect(screen.queryByRole("button", { name: /fix/i })).not.toBeInTheDocument();
  });

  it("sends search, type, blocking, and validation filters to the backend and clears them", async () => {
    render(<Harness initialTab="dependencies"/>);
    await screen.findByText("Task relationships");
    fireEvent.change(screen.getByLabelText("Search template dependencies"), { target: { value: " T001 " } });
    fireEvent.change(screen.getByLabelText("Filter dependency type"), { target: { value: "finish_to_start" } });
    fireEvent.change(screen.getByLabelText("Filter dependency blocking"), { target: { value: "true" } });
    fireEvent.change(screen.getByLabelText("Filter dependency validation"), { target: { value: "invalid" } });
    await waitFor(() => expect(templatesApi.listDependencies.mock.calls.at(-1)[1]).toEqual({
      page: 1,
      page_size: 100,
      search: "T001",
      dependency_type: "finish_to_start",
      blocking: true,
      validation_state: "invalid",
    }));
    fireEvent.click(screen.getByRole("button", { name: /clear/i }));
    await waitFor(() => expect(templatesApi.listDependencies.mock.calls.at(-1)[1]).toEqual({ page: 1, page_size: 100 }));
  });

  it("shows explicit validation warnings without exposing a repair action", async () => {
    templatesApi.listDependencies.mockResolvedValue(dependencyResponse([
      dependency("dep-invalid", 1, { validation_state: "invalid", validation_issues: ["cross_version_reference"] }),
    ], 1, { total: 1, finish_to_start: 1, start_to_start: 0, blocking: 1, validation_issues: 1 }));
    render(<Harness initialTab="dependencies"/>);
    expect(await screen.findByText(/1 relationship require review/i)).toBeInTheDocument();
    expect(screen.getByTestId("dependency-card-dep-invalid")).toHaveTextContent("cross version reference");
    expect(screen.getByText(/No automatic repair or Fix action is available/i)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /fix/i })).not.toBeInTheDocument();
  });

  it("switches to Tasks and focuses the selected dependency task code while preserving the version", async () => {
    render(<Harness initialTab="dependencies"/>);
    await screen.findByText("Task relationships");
    fireEvent.click(screen.getAllByTitle("Open T001 in Tasks")[0]);
    expect(await screen.findByLabelText("Search template tasks")).toHaveValue("T001");
    await waitFor(() => expect(templatesApi.listTasks.mock.calls.at(-1)[0]).toBe("version-published"));
    await waitFor(() => expect(templatesApi.listTasks.mock.calls.at(-1)[1]).toMatchObject({ search: "T001" }));
    fireEvent.click(screen.getByRole("tab", { name: /dependencies/i }));
    expect(await screen.findByText("Task relationships", {}, { timeout: 3000 })).toBeInTheDocument();
    expect(templatesApi.listDependencies.mock.calls.at(-1)[0]).toBe("version-published");
  });

  it("reports dependency authorization failures and leaves Tasks behavior available", async () => {
    const denied = new Error("Template access denied");
    denied.status = 403;
    templatesApi.listDependencies.mockRejectedValueOnce(denied);
    render(<Harness initialTab="dependencies" role="admin"/>);
    expect(await screen.findByText("Template access denied")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("tab", { name: /^tasks/i }));
    expect(await screen.findByTestId("task-card-T001")).toBeInTheDocument();
  });
});
