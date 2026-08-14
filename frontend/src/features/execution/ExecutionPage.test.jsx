import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { projectsApi } from "../../api/projectsApi";
import { taskExecutionApi } from "../../api/taskExecutionApi";
import { ExecutionPage } from "./ExecutionPage";

vi.mock("../../api/projectsApi", () => ({ projectsApi: {
  detail: vi.fn(),
  list: vi.fn(), executionTasks: vi.fn(), dependencies: vi.fn(), externalGates: vi.fn(), detail: vi.fn(),
} }));
vi.mock("../../api/taskExecutionApi", () => ({ taskExecutionApi: {
  list: vi.fn(), detail: vi.fn(), listExternalApprovals: vi.fn(), decideExternalApproval: vi.fn(),
} }));

const activeProjects = [{ id: "p1", name: "Sample Fitout Project", code: "P1", status: "active" }];
const assignedTask = {
  id: "t1", project_id: "p1", baseline_id: "b1", original_code: "T001", template_sequence: 1,
  title: "Freeze approved architectural layout", task_kind: "work", task_class: "standard", lifecycle_status: "in_progress",
  schedule_classification: "execution", planned_start_day: 1, planned_end_day: 1, phase: "Design",
  category: "Planning", evidence_required: false, open_blocker_count: 0, active_support_count: 1,
  created_at: "2026-08-05T00:00:00Z", updated_at: "2026-08-05T00:00:00Z",
};

beforeEach(() => {
  vi.clearAllMocks();
  projectsApi.list.mockResolvedValue(activeProjects);
  // The board resolves the actor's authority from the project's active
  // memberships, so every render needs this even when the test is about
  // something else.
  projectsApi.detail.mockResolvedValue({ id: "p1", memberships: [] });
  projectsApi.executionTasks.mockResolvedValue({
    project_id: "p1", project_name: "Sample Fitout Project", total_tasks: 42, included_task_count: 40, excluded_task_count: 2, tasks: [],
  });
  projectsApi.dependencies.mockResolvedValue({ items: [], total: 12, excluded_warning_count: 0 });
  projectsApi.externalGates.mockResolvedValue([]);
  taskExecutionApi.list.mockResolvedValue([assignedTask]);
  taskExecutionApi.listExternalApprovals.mockResolvedValue([]);
});

describe("ExecutionPage - Internal Employee scoping", () => {
  it("does not fetch the whole-project baseline/dependencies/gates for an Internal Employee", async () => {
    render(<ExecutionPage user={{ role: "internal_employee", id: "u-ie" }}/>);
    expect(await screen.findByText("Freeze approved architectural layout")).toBeInTheDocument();
    expect(projectsApi.executionTasks).not.toHaveBeenCalled();
    expect(projectsApi.dependencies).not.toHaveBeenCalled();
    expect(projectsApi.externalGates).not.toHaveBeenCalled();
  });

  it("shows the project name from the project list, not from the (skipped) whole-project fetch", async () => {
    render(<ExecutionPage user={{ role: "internal_employee", id: "u-ie" }}/>);
    expect(await screen.findByText("Sample Fitout Project")).toBeInTheDocument();
    expect(screen.getByText("Your assigned tasks")).toBeInTheDocument();
  });

  it("hides the whole-project metric cards and the Dependencies/External Approvals sub-tabs", async () => {
    render(<ExecutionPage user={{ role: "internal_employee", id: "u-ie" }}/>);
    await screen.findByText("Freeze approved architectural layout");
    expect(screen.queryByText("Total tasks")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /dependencies/i })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /external approvals/i })).not.toBeInTheDocument();
  });

  it("still shows the full whole-project view for a Supervisor", async () => {
    render(<ExecutionPage user={{ role: "supervisor", id: "u-sup" }}/>);
    await waitFor(() => expect(projectsApi.executionTasks).toHaveBeenCalledWith("p1"));
    expect(await screen.findByText("Total tasks")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /dependencies/i })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /external approvals/i })).toBeInTheDocument();
  });
});

// U18's verification: approving the last pending approval on a blocked task
// flips it to ready without the user reloading anything. This is the whole
// point of the unit - the approvals endpoints and the readiness engine both
// shipped weeks ago and nothing on this surface could reach either.
describe("ExecutionPage - external approval decisions", () => {
  const projectManager = { role: "project_manager", id: "u-pm" };
  const blockedTask = {
    ...assignedTask, lifecycle_status: "planned",
    readiness: {
      state: "blocked",
      reasons: [{ kind: "approval", subject_id: "a1", detail: "Waiting on external approval FIRE-NOC (pending).", blocking: true }],
      advisories: [],
    },
  };
  const releasedTask = { ...blockedTask, readiness: { state: "ready", reasons: [], advisories: [] } };
  const approval = {
    id: "a1", project_id: "p1", project_gate_id: "g1", gate_code: "FIRE-NOC", gate_name: "Fire NOC",
    status: "pending", blocking: true, coverage_state: "exact", coverage_text: null,
    covered_task_ids: ["t1"], decided_by: null, decided_by_name: null, decided_at: null,
  };

  beforeEach(() => {
    projectsApi.detail.mockResolvedValue({
      id: "p1", memberships: [{ id: "m1", user_id: "u-pm", project_role: "project_manager", ends_at: null }],
    });
    taskExecutionApi.listExternalApprovals.mockResolvedValue([approval]);
    taskExecutionApi.decideExternalApproval.mockResolvedValue({});
  });

  it("flips a blocked task to ready once its last approval is granted, with no reload", async () => {
    taskExecutionApi.list
      .mockResolvedValueOnce([blockedTask])
      .mockResolvedValue([releasedTask]);
    render(<ExecutionPage user={projectManager}/>);
    // Scoped to the row: "Blocked" is also a count tile above the board now,
    // and this assertion is about the task's own readiness pill.
    const row = await screen.findByRole("button", { name: /freeze approved architectural layout/i });
    expect(within(row).getByText("Blocked")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /external approvals/i }));
    fireEvent.click(await screen.findByRole("button", { name: "Approve" }));
    fireEvent.click(await screen.findByRole("button", { name: "Confirm approval" }));
    await waitFor(() => expect(taskExecutionApi.decideExternalApproval).toHaveBeenCalledWith(
      "p1", "a1", { decision: "approved", reason: null },
    ));

    fireEvent.click(screen.getByRole("button", { name: /^tasks$/i }));
    const releasedRow = await screen.findByRole("button", { name: /freeze approved architectural layout/i });
    expect(within(releasedRow).getByText("Ready to start")).toBeInTheDocument();
    expect(within(releasedRow).queryByText("Blocked")).not.toBeInTheDocument();
  });

  // U16: the timeline fetches its own tasks rather than reading the array the
  // board handed up, so it does not depend on Tasks being the default tab.
  it("opens the timeline tab and loads the schedule itself", async () => {
    taskExecutionApi.list.mockResolvedValue([{
      ...assignedTask, phase: "Design",
      planned_start_date: "2026-08-01", planned_end_date: "2026-08-05",
      actual_start_at: "2026-08-01T09:00:00Z", actual_finish_at: "2026-08-04T17:00:00Z",
      variance: { status: "early", variance_days: -1, days: 1, measured_against: "actual_finish" },
    }]);
    render(<ExecutionPage user={projectManager}/>);
    fireEvent.click(await screen.findByRole("button", { name: /^timeline$/i }));
    expect(await screen.findByText("Baseline vs actual")).toBeInTheDocument();
    expect(screen.getByLabelText("Baseline for T001")).toBeInTheDocument();
    expect(screen.getByLabelText("Actual for T001")).toBeInTheDocument();
  });

  it("renders the tab from the execution layer, not from the planning gates", async () => {
    // The planning-layer gates are still read, but only to explain an empty
    // list (how many are awaiting an applicability decision). What is
    // RENDERED as approvals comes from the execution-layer endpoint - that
    // was the point of the switch, and it is what this pins.
    projectsApi.externalGates.mockResolvedValue({ items: [{ id: "g1", applicability_state: "applicable" }] });
    render(<ExecutionPage user={projectManager}/>);
    fireEvent.click(await screen.findByRole("button", { name: /external approvals/i }));
    expect(await screen.findByText("Fire NOC")).toBeInTheDocument();
    expect(taskExecutionApi.listExternalApprovals).toHaveBeenCalledWith("p1");
  });

  it("explains an empty tab by naming the gates still awaiting review", async () => {
    taskExecutionApi.listExternalApprovals.mockResolvedValue([]);
    projectsApi.externalGates.mockResolvedValue({
      items: Array.from({ length: 32 }, (_, index) => ({ id: `g${index}`, applicability_state: "pending_review" })),
    });
    render(<ExecutionPage user={projectManager}/>);
    fireEvent.click(await screen.findByRole("button", { name: /external approvals/i }));
    expect(await screen.findByText(/32 external approvals are awaiting applicability review/i)).toBeInTheDocument();
  });
});

// U19: the header tiles used to be planning figures sitting above an
// execution board, so they described a different set of tasks than the rows
// beneath them (R26). They now count the very array the board drew.
describe("ExecutionPage - readiness counts, filters and accelerate list", () => {
  const supervisor = { role: "supervisor", id: "u-sup" };
  const isoOffsetDays = days => {
    const date = new Date();
    date.setUTCDate(date.getUTCDate() + days);
    return date.toISOString().slice(0, 10);
  };
  const task = (id, state, extra = {}) => ({
    ...assignedTask, id, original_code: id.toUpperCase(), title: `Task ${id}`,
    lifecycle_status: "planned", readiness: { state, reasons: [], advisories: [] }, ...extra,
  });

  // Two ready (one of them startable early), one blocked, one completed.
  const boardTasks = [
    task("t1", "ready", { planned_start_date: isoOffsetDays(12), title: "Pour slab" }),
    task("t2", "ready", { planned_start_date: isoOffsetDays(-2), title: "Site setup" }),
    task("t3", "blocked", { planned_start_date: isoOffsetDays(5), title: "Fit ceiling" }),
    task("t4", "completed", { planned_start_date: isoOffsetDays(-9), title: "Handover pack", lifecycle_status: "completed" }),
  ];

  const boardRows = () => screen.getAllByRole("button", { name: /^T\d/i });
  // The accelerate panel deliberately ignores the board's readiness filter -
  // it answers a different question - so assertions about what the FILTER did
  // have to look at the rows, not at the page.
  const boardTitles = () => boardRows().map(row => row.querySelector("strong")?.textContent);
  // Scoped to the summary group: "Ready" and "Blocked" are also filter
  // button labels, which is fine on screen but ambiguous to a text query.
  const tile = label => within(screen.getByRole("group", { name: "Readiness summary" })).getByText(label).closest("article");
  const acceleratePanel = async () => (await screen.findByRole("heading", { name: /could start early/i })).closest("section");

  beforeEach(() => {
    taskExecutionApi.list.mockResolvedValue(boardTasks);
  });

  it("counts the execution rows the board drew, not the planning read model", async () => {
    // The planning read model claims 42/40/2 - deliberately nothing like the
    // four execution rows, so a tile still reading from it would be obvious.
    render(<ExecutionPage user={supervisor}/>);
    await screen.findAllByText("Pour slab");
    expect(within(tile("Total tasks")).getByText("4")).toBeInTheDocument();
    expect(within(tile("Ready")).getByText("2")).toBeInTheDocument();
    expect(within(tile("Blocked")).getByText("1")).toBeInTheDocument();
    expect(screen.queryByText("42")).not.toBeInTheDocument();
  });

  it("lists a ready task whose planned start is still in the future as startable early", async () => {
    render(<ExecutionPage user={supervisor}/>);
    // Both the panel and the board row carry the title, so wait for the data
    // to land before scoping to the panel.
    await screen.findAllByText("Pour slab");
    const panel = await acceleratePanel();
    expect(within(panel).getByText("Pour slab")).toBeInTheDocument();
    expect(within(panel).getByText("1")).toBeInTheDocument();
  });

  // Both of these wait for the list to actually populate first. Asserting
  // absence against a panel that has not loaded yet would pass for the wrong
  // reason and keep passing if the filter broke entirely.
  it("leaves out a ready task whose planned start has already passed", async () => {
    render(<ExecutionPage user={supervisor}/>);
    await screen.findAllByText("Pour slab");
    const panel = await acceleratePanel();
    expect(within(panel).getByText("Pour slab")).toBeInTheDocument();
    expect(within(panel).queryByText("Site setup")).not.toBeInTheDocument();
  });

  it("leaves out a blocked task even though its planned start is in the future", async () => {
    render(<ExecutionPage user={supervisor}/>);
    await screen.findAllByText("Pour slab");
    const panel = await acceleratePanel();
    expect(within(panel).getByText("Pour slab")).toBeInTheDocument();
    expect(within(panel).queryByText("Fit ceiling")).not.toBeInTheDocument();
  });

  it("explains an empty accelerate list rather than showing a bare heading", async () => {
    taskExecutionApi.list.mockResolvedValue([boardTasks[1], boardTasks[2]]);
    render(<ExecutionPage user={supervisor}/>);
    await screen.findByText("Site setup");
    const panel = await acceleratePanel();
    expect(within(panel).getByText(/nothing can be pulled forward/i)).toBeInTheDocument();
  });

  it("filters the board to blocked tasks only", async () => {
    render(<ExecutionPage user={supervisor}/>);
    await screen.findAllByText("Pour slab");
    fireEvent.click(screen.getByRole("button", { name: "Blocked" }));
    await waitFor(() => expect(boardRows()).toHaveLength(1));
    expect(boardTitles()).toEqual(["Fit ceiling"]);
  });

  it("filters the board to ready tasks only", async () => {
    render(<ExecutionPage user={supervisor}/>);
    await screen.findAllByText("Pour slab");
    fireEvent.click(screen.getByRole("button", { name: "Ready" }));
    await waitFor(() => expect(boardRows()).toHaveLength(2));
    expect(boardTitles()).toEqual(["Pour slab", "Site setup"]);
  });

  it("restores every task when the filter is cleared", async () => {
    render(<ExecutionPage user={supervisor}/>);
    await screen.findAllByText("Pour slab");
    fireEvent.click(screen.getByRole("button", { name: "Blocked" }));
    await waitFor(() => expect(boardRows()).toHaveLength(1));
    fireEvent.click(screen.getByRole("button", { name: "All" }));
    await waitFor(() => expect(boardRows()).toHaveLength(4));
  });

  // The verification for this unit: the number above the board equals the
  // number of rows in it, which was not true before.
  it("keeps each count equal to the rows its filter produces", async () => {
    render(<ExecutionPage user={supervisor}/>);
    await screen.findAllByText("Pour slab");
    for (const [label, filter] of [["Ready", "Ready"], ["Blocked", "Blocked"]]) {
      const expected = Number(within(tile(label)).getByText(/^\d+$/).textContent);
      fireEvent.click(screen.getByRole("button", { name: filter }));
      await waitFor(() => expect(boardRows()).toHaveLength(expected));
    }
  });

  it("says which filter emptied the board rather than claiming the project has no tasks", async () => {
    taskExecutionApi.list.mockResolvedValue([boardTasks[0]]);
    render(<ExecutionPage user={supervisor}/>);
    await screen.findAllByText("Pour slab");
    fireEvent.click(screen.getByRole("button", { name: "Blocked" }));
    expect(await screen.findByText("No blocked tasks")).toBeInTheDocument();
    expect(screen.queryByText("No execution tasks yet")).not.toBeInTheDocument();
  });

  it("combines the readiness filter with the search box", async () => {
    render(<ExecutionPage user={supervisor}/>);
    await screen.findAllByText("Pour slab");
    fireEvent.click(screen.getByRole("button", { name: "Ready" }));
    fireEvent.change(screen.getByPlaceholderText(/search task code/i), { target: { value: "slab" } });
    await waitFor(() => expect(boardRows()).toHaveLength(1));
    expect(boardTitles()).toEqual(["Pour slab"]);
  });
});
