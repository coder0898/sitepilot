import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { taskExecutionApi } from "../../api/taskExecutionApi";
import { PhaseOverviewDrawer, plannedDate } from "./components/PhaseOverviewDrawer";
import { ProjectOverviewPane, selectRelevantPhases } from "./components/ProjectOverviewPane";

vi.mock("../../api/taskExecutionApi", () => ({ taskExecutionApi: { list: vi.fn() } }));

const phase = (name, completed, total, status, inProgress = 0) => ({
  phase: name, total, completed, in_progress: inProgress,
  not_started: total - completed - inProgress,
  pct: total ? Math.round((completed / total) * 100) : 0, status,
});

// Shaped like the 45-day template: many phases, most of them tiny.
const manyPhases = [
  phase("Pre-Activation", 7, 7, "completed"),
  phase("Mobilisation", 8, 8, "completed"),
  phase("Dismantling", 4, 4, "completed"),
  phase("Civil", 1, 3, "in_progress", 1),
  phase("Coordination", 0, 2, "not_started"),
  phase("MEP First Fix", 0, 6, "not_started"),
  phase("Inspection", 0, 2, "not_started"),
  phase("Handover", 0, 5, "not_started"),
];

const project = { id: "p1", name: "Test2", start_date: "2026-08-06", target_handover_date: "2026-10-21" };
const summary = {
  progress_pct: 25, total_count: 37, completed_count: 20,
  blocked_count: 0, delayed_count: 1, pending_approvals: 0, no_update_count: 0,
  phases: manyPhases,
};

beforeEach(() => {
  vi.clearAllMocks();
  taskExecutionApi.list.mockResolvedValue([
    { id: "t1", original_code: "T012", title: "Blockwork", phase: "Civil", lifecycle_status: "completed", planned_start_day: 3 },
    { id: "t2", original_code: "T013", title: "Screed", phase: "Civil", lifecycle_status: "in_progress", planned_start_day: 5 },
    { id: "t3", original_code: "T020", title: "Conduiting", phase: "MEP First Fix", lifecycle_status: "planned", planned_start_day: 9 },
  ]);
});

describe("Relevance-based phase selection", () => {
  it("shows work in flight and what is next, not the first phases in the schedule", () => {
    const picked = selectRelevantPhases(manyPhases).map(item => item.phase);
    expect(picked).toEqual(["Civil", "Coordination", "MEP First Fix", "Inspection", "Handover"]);
    // The three finished opening phases are exactly what the old panel wasted
    // its five rows on.
    expect(picked).not.toContain("Pre-Activation");
  });

  it("keeps the chosen phases in schedule order", () => {
    const source = [
      phase("Alpha", 0, 4, "not_started"),
      phase("Beta", 2, 4, "in_progress", 1),
      phase("Gamma", 0, 4, "not_started"),
    ];
    // Beta is picked first by relevance but must still render between Alpha
    // and Gamma, where the reader expects it.
    expect(selectRelevantPhases(source, 3).map(item => item.phase)).toEqual(["Alpha", "Beta", "Gamma"]);
  });

  it("falls back to the most recently finished phases when everything is done", () => {
    const done = manyPhases.map(item => ({ ...item, status: "completed", completed: item.total, pct: 100 }));
    const picked = selectRelevantPhases(done, 3).map(item => item.phase);
    // The last three in schedule order - the work that just finished, not the
    // work that finished weeks ago.
    expect(picked).toEqual(["MEP First Fix", "Inspection", "Handover"]);
  });

  it("returns everything when a project has fewer phases than the limit", () => {
    const few = [phase("Alpha", 0, 2, "not_started"), phase("Beta", 1, 2, "in_progress")];
    expect(selectRelevantPhases(few)).toHaveLength(2);
  });

  it("handles a project with no phase breakdown", () => {
    expect(selectRelevantPhases([])).toEqual([]);
    expect(selectRelevantPhases(undefined)).toEqual([]);
  });
});

describe("Execution progress panel", () => {
  it("caps the phase list and offers the rest behind one control", async () => {
    render(<ProjectOverviewPane project={project} summary={summary} onOpenPane={vi.fn()}/>);
    expect(screen.getAllByText(/^\d+\/\d+$/)).toHaveLength(5);
    expect(screen.getByRole("button", { name: /view all 8 phases/i })).toBeInTheDocument();
  });

  it("leads each phase with its task counts, not just a percentage", () => {
    render(<ProjectOverviewPane project={project} summary={summary} onOpenPane={vi.fn()}/>);
    expect(screen.getByText("1/3")).toBeInTheDocument();
    expect(screen.getByText("0/6")).toBeInTheDocument();
  });

  it("hides the control when every phase already fits", () => {
    const few = { ...summary, phases: [phase("Alpha", 0, 2, "not_started")] };
    render(<ProjectOverviewPane project={project} summary={few} onOpenPane={vi.fn()}/>);
    expect(screen.queryByRole("button", { name: /view all/i })).not.toBeInTheDocument();
  });

  it("opens the drawer from the panel", async () => {
    render(<ProjectOverviewPane project={project} summary={summary} onOpenPane={vi.fn()}/>);
    fireEvent.click(screen.getByRole("button", { name: /view all 8 phases/i }));
    expect(await screen.findByRole("dialog", { name: /phase overview/i })).toBeInTheDocument();
  });
});

describe("Phase overview drawer", () => {
  function open() {
    return render(<PhaseOverviewDrawer project={project} summary={summary} onClose={vi.fn()}/>);
  }

  it("lists every phase with its counts and status", () => {
    open();
    expect(screen.getByText("Showing 8 of 8 phases")).toBeInTheDocument();
    expect(screen.getAllByText("Completed").length).toBeGreaterThan(0);
    expect(screen.getAllByText("Not started").length).toBeGreaterThan(0);
  });

  it("filters by search and by status", () => {
    open();
    fireEvent.change(screen.getByLabelText("Search phases"), { target: { value: "mep" } });
    expect(screen.getByText("Showing 1 of 8 phases")).toBeInTheDocument();

    fireEvent.change(screen.getByLabelText("Search phases"), { target: { value: "" } });
    fireEvent.change(screen.getByLabelText("Filter phases by status"), { target: { value: "completed" } });
    expect(screen.getByText("Showing 3 of 8 phases")).toBeInTheDocument();
  });

  it("draws no progress bar for a phase of one or two tasks", () => {
    open();
    // Coordination holds 2 tasks: the status chip already says all there is
    // to say, so a bar would be a yes/no drawn as a chart.
    const row = screen.getByText("Coordination").closest("button");
    expect(within(row).getByText("—")).toBeInTheDocument();
    const civil = screen.getByText("Civil").closest("button");
    expect(within(civil).getByText("33%")).toBeInTheDocument();
  });

  it("loads tasks once, on first expand", async () => {
    open();
    expect(taskExecutionApi.list).not.toHaveBeenCalled();

    fireEvent.click(screen.getByText("Civil").closest("button"));
    expect(await screen.findByText("Blockwork")).toBeInTheDocument();
    expect(screen.getByText("Screed")).toBeInTheDocument();
    expect(screen.queryByText("Conduiting")).not.toBeInTheDocument();

    fireEvent.click(screen.getByText("Civil").closest("button"));
    fireEvent.click(screen.getByText("MEP First Fix").closest("button"));
    expect(await screen.findByText("Conduiting")).toBeInTheDocument();
    await waitFor(() => expect(taskExecutionApi.list).toHaveBeenCalledTimes(1));
  });

  it("turns template day offsets into real dates", async () => {
    open();
    fireEvent.click(screen.getByText("Civil").closest("button"));
    // Day 1 is the start date itself, so day 3 of a 06 Aug project is 08 Aug.
    expect(await screen.findByText("08 Aug 2026")).toBeInTheDocument();
    expect(plannedDate("2026-08-06", 1)).toBe("06 Aug 2026");
    expect(plannedDate("2026-08-06", null)).toBeNull();
  });

  it("survives a failed task load without breaking the drawer", async () => {
    taskExecutionApi.list.mockRejectedValue(new Error("network"));
    open();
    fireEvent.click(screen.getByText("Civil").closest("button"));
    expect(await screen.findByText("No tasks in this phase.")).toBeInTheDocument();
  });
});
