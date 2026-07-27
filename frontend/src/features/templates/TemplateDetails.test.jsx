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

function task(code, sequence, overrides = {}) {
  const preActivation = sequence <= 7;
  const day = preActivation ? null : sequence >= 97 ? 45 : sequence - 7;
  return {
    id: `id-${code}`,
    code,
    sequence_no: sequence,
    title: `Task ${code}`,
    description: `Description for ${code}`,
    schedule_classification: preActivation ? "pre_activation" : "execution",
    planned_start_day: day,
    planned_end_day: day,
    phase: preActivation ? "Pre-Activation" : sequence >= 97 ? "Closeout" : "Execution",
    category: preActivation ? "Approvals" : sequence >= 97 ? "Handover" : "Site Works",
    applicability: code === "T098" ? "conditional" : "mandatory",
    task_class: preActivation ? "control" : "work",
    task_kind: preActivation ? "approval" : "execution",
    evidence_required: !preActivation,
    duration_days: 1,
    validation_state: "valid",
    validation_issues: [],
    ...overrides,
  };
}

const keyTasks = [task("T001", 1), task("T007", 7), task("T008", 8), task("T097", 97), task("T098", 98), task("T099", 99)];
const taskResponse = (items = keyTasks, overrides = {}) => ({
  items,
  pagination: { page: 1, page_size: 20, total: items.length, total_pages: items.length ? 1 : 0, ...overrides },
});

function errorWithStatus(message, status) {
  const error = new Error(message);
  error.status = status;
  return error;
}

function Harness({ role = "admin", versionId = "version-published", onBack = vi.fn() }) {
  const [tab, setTab] = useState("tasks");
  return <TemplateDetails versionId={versionId} user={{ role }} onBack={onBack} activeTemplateTab={tab} onTabChange={setTab} debounceMs={0}/>;
}

beforeEach(() => {
  vi.clearAllMocks();
  templatesApi.getVersion.mockResolvedValue(summary);
  templatesApi.listTasks.mockResolvedValue(taskResponse());
  templatesApi.listDependencies.mockResolvedValue({ items: [], pagination: { page: 1, page_size: 100, total: 0, total_pages: 0 }, summary: { total: 0, finish_to_start: 0, start_to_start: 0, blocking: 0, validation_issues: 0 } });
  templatesApi.listGates.mockResolvedValue({ items: [], pagination: { page: 1, page_size: 100, total: 0, total_pages: 0 } });
});

describe("TemplateDetails", () => {
  it("renders the governed header, summary, grouped key tasks, desktop rows, mobile cards, and back action", async () => {
    const onBack = vi.fn();
    render(<Harness onBack={onBack}/>);
    expect(await screen.findByText("Workved 45-Day Interior Delivery")).toBeInTheDocument();
    expect(screen.getByText("WORKVED-45")).toBeInTheDocument();
    expect(screen.getByText("Current published")).toBeInTheDocument();
    expect(screen.getAllByText("99").length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText("38").length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText("32").length).toBeGreaterThanOrEqual(1);
    expect(await screen.findByRole("heading", { name: "Pre-Activation" })).toBeInTheDocument();
    expect(screen.getByText("Day 1-45 Execution")).toBeInTheDocument();
    expect(screen.getByTestId("task-row-T001")).toBeInTheDocument();
    expect(screen.getByTestId("task-card-T008")).toBeInTheDocument();
    expect(screen.getByTestId("task-card-T098")).toHaveTextContent("conditional");
    expect(templatesApi.getVersion).toHaveBeenCalledTimes(1);
    expect(templatesApi.listTasks).toHaveBeenCalledTimes(1);
    expect(screen.queryByRole("button", { name: /create|edit|delete|archive/i })).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /back to templates/i }));
    expect(onBack).toHaveBeenCalledOnce();
  });

  it("preserves backend order and sends all API filters after trimming text", async () => {
    render(<Harness/>);
    await screen.findByTestId("task-card-T008");
    const cards = screen.getAllByTestId(/task-card-/).map(node => node.dataset.testid);
    expect(cards).toEqual(keyTasks.map(item => `task-card-${item.code}`));
    fireEvent.change(screen.getByLabelText("Search template tasks"), { target: { value: " electrical " } });
    fireEvent.change(screen.getByLabelText("Filter schedule classification"), { target: { value: "execution" } });
    fireEvent.change(screen.getByLabelText("Filter task phase"), { target: { value: " closeout " } });
    fireEvent.change(screen.getByLabelText("Filter task category"), { target: { value: " handover " } });
    fireEvent.change(screen.getByLabelText("Filter applicability"), { target: { value: "conditional" } });
    await waitFor(() => expect(templatesApi.listTasks.mock.calls.at(-1)[1]).toMatchObject({
      search: "electrical",
      schedule_classification: "execution",
      phase: "closeout",
      category: "handover",
      applicability: "conditional",
      page: 1,
    }));
    fireEvent.click(screen.getByRole("button", { name: /clear/i }));
    await waitFor(() => expect(templatesApi.listTasks.mock.calls.at(-1)[1]).toEqual({ page: 1, page_size: 20 }));
  });

  it("loads subsequent pages without replacing earlier tasks", async () => {
    templatesApi.listTasks.mockImplementation((_version, params) => params.page === 1
      ? Promise.resolve(taskResponse([task("T001", 1)], { total: 2, total_pages: 2 }))
      : Promise.resolve(taskResponse([task("T008", 8)], { page: 2, total: 2, total_pages: 2 })));
    render(<Harness/>);
    expect(await screen.findByTestId("task-card-T001")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /load more tasks/i }));
    expect(await screen.findByTestId("task-card-T008")).toBeInTheDocument();
    expect(screen.getByTestId("task-card-T001")).toBeInTheDocument();
  });

  it("distinguishes loading, empty, and filtered no-match states", async () => {
    let resolveVersion;
    templatesApi.getVersion.mockReturnValue(new Promise(resolve => { resolveVersion = resolve; }));
    const first = render(<Harness/>);
    expect(screen.getByText("Loading template details...")).toBeInTheDocument();
    resolveVersion(summary);
    await screen.findByText("Workved 45-Day Interior Delivery");
    first.unmount();

    templatesApi.getVersion.mockResolvedValue(summary);
    templatesApi.listTasks.mockResolvedValue(taskResponse([]));
    render(<Harness/>);
    expect(await screen.findByText("No tasks stored for this version")).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("Search template tasks"), { target: { value: "missing" } });
    expect(await screen.findByText("No tasks match these filters")).toBeInTheDocument();
  });

  it("shows task API errors and retries successfully", async () => {
    templatesApi.listTasks.mockRejectedValueOnce(new Error("Task service unavailable")).mockResolvedValueOnce(taskResponse());
    render(<Harness/>);
    expect(await screen.findByRole("alert")).toHaveTextContent("Task service unavailable");
    fireEvent.click(screen.getByRole("button", { name: /retry/i }));
    expect(await screen.findByTestId("task-card-T008")).toBeInTheDocument();
  });

  it("shows validation warnings and issues without hiding the task", async () => {
    const invalid = task("T008", 8, { validation_state: "invalid", validation_issues: ["missing_execution_day"] });
    templatesApi.listTasks.mockResolvedValue(taskResponse([invalid]));
    render(<Harness/>);
    expect(await screen.findByText(/1 loaded task require validation/i)).toBeInTheDocument();
    expect(screen.getByTestId("task-card-T008")).toHaveTextContent("missing execution day");
  });

  it("allows Super Admin draft details but reports a non-revealing Admin draft denial", async () => {
    templatesApi.getVersion.mockResolvedValueOnce({ ...summary, status: "draft", is_current_published: false, published_at: null });
    const superView = render(<Harness role="super_admin" versionId="version-draft"/>);
    expect((await screen.findAllByText("draft")).length).toBeGreaterThan(0);
    superView.unmount();
    templatesApi.listTasks.mockClear();

    templatesApi.getVersion.mockRejectedValueOnce(errorWithStatus("Template version not found.", 404));
    render(<Harness role="admin" versionId="version-draft"/>);
    expect(await screen.findByText("Template version not found")).toBeInTheDocument();
    expect(screen.getByText(/does not exist or is not available to your role/i)).toBeInTheDocument();
    expect(templatesApi.listTasks).not.toHaveBeenCalled();
  });

  it("reports an unauthorized detail request as an expired session", async () => {
    templatesApi.getVersion.mockRejectedValueOnce(errorWithStatus("Login required.", 401));
    render(<Harness/>);
    expect(await screen.findByText("Session expired")).toBeInTheDocument();
  });

  it("loads the dependency and external-gate tabs", async () => {
    render(<Harness/>);
    await screen.findByTestId("task-card-T001");
    fireEvent.click(screen.getByRole("tab", { name: /dependencies/i }));
    expect(await screen.findByText("No dependencies stored for this version")).toBeInTheDocument();
    expect(templatesApi.listDependencies).toHaveBeenCalledWith("version-published", { page: 1, page_size: 100 }, expect.any(Object));
    fireEvent.click(screen.getByRole("tab", { name: /external gates/i }));
    expect(await screen.findByText("No external gates stored for this version")).toBeInTheDocument();
    expect(templatesApi.listGates).toHaveBeenCalledWith("version-published", { page: 1, page_size: 100 }, expect.any(Object));
  });
});