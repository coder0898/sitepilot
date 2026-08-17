import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { projectsApi } from "../../api/projectsApi";
import { taskExecutionApi } from "../../api/taskExecutionApi";
import { ExecutionCalendarView } from "./components/ExecutionCalendarView";

vi.mock("../../api/projectsApi", () => ({ projectsApi: { detail: vi.fn() } }));
vi.mock("../../api/taskExecutionApi", () => ({ taskExecutionApi: { list: vi.fn(), detail: vi.fn(), listExternalApprovals: vi.fn() } }));

const admin = { id: "u-adm", role: "admin" };

const todayIso = new Date().toISOString().slice(0, 10);

// Dated by default - the grid is the calendar's primary surface, and the
// Pre-Activation Checklist (undated tasks) is now collapsed by default, so
// tests that aren't specifically about the checklist should exercise the
// grid. Tests that need an undated task override planned_start_date/
// planned_end_date back to null explicitly.
const task = (overrides = {}) => ({
  id: "t1", project_id: "p1", baseline_id: "b1", original_code: "T001", template_sequence: 1,
  title: "Pour slab", task_kind: "work", task_class: "standard", lifecycle_status: "planned",
  schedule_classification: "execution", planned_start_day: 1, planned_end_day: 1,
  planned_start_date: todayIso, planned_end_date: todayIso, phase: "Civil", category: "Structure",
  evidence_required: false, open_blocker_count: 0, active_support_count: 0,
  readiness: { state: "ready", reasons: [], advisories: [] },
  variance: null,
  created_at: "2026-08-01T00:00:00Z", updated_at: "2026-08-01T00:00:00Z",
  ...overrides,
});

beforeEach(() => {
  vi.clearAllMocks();
  projectsApi.detail.mockResolvedValue({ id: "p1", memberships: [] });
  taskExecutionApi.listExternalApprovals.mockResolvedValue([]);
});

// U19's invariant, carried forward from the old flat board: the summary
// tiles and the rows on screen must count the same set of tasks.
describe("ExecutionCalendarView", () => {
  it("counts tasks into the 6 summary tiles from the same array it renders", async () => {
    taskExecutionApi.list.mockResolvedValue([
      task({ id: "t1", lifecycle_status: "ready", readiness: { state: "ready", reasons: [], advisories: [] } }),
      task({ id: "t2", lifecycle_status: "in_progress", readiness: { state: "in_progress", reasons: [], advisories: [] } }),
      task({ id: "t3", lifecycle_status: "planned", readiness: { state: "blocked", reasons: [], advisories: [] } }),
      task({ id: "t4", lifecycle_status: "completed", readiness: { state: "completed", reasons: [], advisories: [] } }),
    ]);
    render(<ExecutionCalendarView projectId="p1" user={admin}/>);
    const group = await screen.findByRole("group", { name: /execution summary/i });
    expect(within(group).getByText("4")).toBeInTheDocument(); // Total
    expect(within(group).getAllByText("1").length).toBeGreaterThanOrEqual(3); // ready/in progress/blocked each 1
  });

  it("narrows the list by the status filter", async () => {
    taskExecutionApi.list.mockResolvedValue([
      task({ id: "t1", title: "Pour slab", readiness: { state: "blocked", reasons: [], advisories: [] } }),
      task({ id: "t2", title: "Fit ceiling", readiness: { state: "ready", reasons: [], advisories: [] } }),
    ]);
    render(<ExecutionCalendarView projectId="p1" user={admin}/>);
    await screen.findByText("Pour slab");
    fireEvent.change(screen.getByLabelText(/filter by status/i), { target: { value: "blocked" } });
    await waitFor(() => expect(screen.queryByText("Fit ceiling")).not.toBeInTheDocument());
    expect(screen.getByText("Pour slab")).toBeInTheDocument();
  });

  it("narrows the list by search", async () => {
    taskExecutionApi.list.mockResolvedValue([
      task({ id: "t1", title: "Pour slab" }),
      task({ id: "t2", title: "Fit ceiling" }),
    ]);
    render(<ExecutionCalendarView projectId="p1" user={admin}/>);
    await screen.findByText("Pour slab");
    fireEvent.change(screen.getByPlaceholderText(/search task code/i), { target: { value: "ceiling" } });
    await waitFor(() => expect(screen.queryByText("Pour slab")).not.toBeInTheDocument());
    expect(screen.getByText("Fit ceiling")).toBeInTheDocument();
  });

  it("opens the task detail drawer when a task is clicked, and closes it", async () => {
    taskExecutionApi.list.mockResolvedValue([task({ title: "Pour slab" })]);
    taskExecutionApi.detail.mockResolvedValue({
      ...task({ title: "Pour slab" }), description: "Structural slab pour.",
      predecessors: [], progress_updates: [], verifications: [], approvals: [],
      blockers: [], delays: [], support_assignments: [], audit_events: [],
    });
    render(<ExecutionCalendarView projectId="p1" user={admin}/>);
    fireEvent.click(await screen.findByText("Pour slab"));
    expect(await screen.findByText("Structural slab pour.")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /close task detail/i }));
    await waitFor(() => expect(screen.queryByText("Structural slab pour.")).not.toBeInTheDocument());
  });

  it("renders dated tasks on the day-grid with a today marker", async () => {
    const todayIso = new Date().toISOString().slice(0, 10);
    taskExecutionApi.list.mockResolvedValue([task({ title: "Pour slab", planned_start_date: todayIso, planned_end_date: todayIso })]);
    render(<ExecutionCalendarView projectId="p1" user={admin}/>);
    expect(await screen.findByLabelText("Today")).toBeInTheDocument();
    expect(screen.getByText(/Pour slab/)).toBeInTheDocument();
  });

  // Regression: a task dated only by its actuals (no planned_start_date) is
  // "dated" by isDated's definition, but the grid draws PLANNED bars and
  // must not treat it as gridworthy - it belongs in the Pre-Activation
  // Checklist instead, not crash `gridColumnFor` on a null planned range.
  it("renders a task with only an actual start date in the Pre-Activation Checklist, not the grid, collapsed by default", async () => {
    taskExecutionApi.list.mockResolvedValue([task({
      title: "Site setup", planned_start_date: null, planned_end_date: null,
      actual_start_at: "2026-08-01T09:00:00Z", actual_finish_at: null,
      lifecycle_status: "in_progress",
    })]);
    render(<ExecutionCalendarView projectId="p1" user={admin}/>);
    expect(await screen.findByText("Pre-Activation Checklist")).toBeInTheDocument();
    expect(screen.getByText("1 task waiting to be scheduled")).toBeInTheDocument();
    // Collapsed by default - only the header and its summary chips show, not
    // the task list itself.
    expect(screen.queryByText("Site setup")).not.toBeInTheDocument();
    expect(screen.queryByText(/not yet dated/i)).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /pre-activation checklist/i }));
    expect(await screen.findByText("Site setup")).toBeInTheDocument();
  });

  it("shows a Ready/Blocked/In Progress status breakdown on the Pre-Activation Checklist header", async () => {
    const undatedTasks = Array.from({ length: 7 }, (_, index) => task({
      id: `u${index}`, title: `Undated task ${index}`, planned_start_date: null, planned_end_date: null,
      readiness: { state: index < 2 ? "blocked" : "ready", reasons: [], advisories: [] },
    }));
    taskExecutionApi.list.mockResolvedValue(undatedTasks);
    render(<ExecutionCalendarView projectId="p1" user={admin}/>);
    expect(await screen.findByText("7 tasks waiting to be scheduled")).toBeInTheDocument();
    expect(screen.getByText("2 Blocked")).toBeInTheDocument();
    expect(screen.getByText("5 Ready")).toBeInTheDocument();
    expect(screen.getByText("0 In Progress")).toBeInTheDocument();
  });

  it("shows an empty state when the project has no execution tasks", async () => {
    taskExecutionApi.list.mockResolvedValue([]);
    render(<ExecutionCalendarView projectId="p1" user={admin}/>);
    expect(await screen.findByText("No execution tasks yet")).toBeInTheDocument();
  });

  // The task title must live in the fixed left table, never inside the
  // timeline bar itself (which has no visible text, only a tooltip) - the
  // exact complaint that drove this rewrite: titles getting cut off inside
  // tiny rounded pills.
  it("puts the task title in the left table, not as visible text on the bar", async () => {
    const todayIso = new Date().toISOString().slice(0, 10);
    taskExecutionApi.list.mockResolvedValue([task({ title: "Install door frames and hardware", planned_start_date: todayIso, planned_end_date: todayIso })]);
    render(<ExecutionCalendarView projectId="p1" user={admin}/>);
    const titleEl = await screen.findByText("Install door frames and hardware");
    expect(titleEl.closest("button")).toHaveAttribute("title", expect.stringContaining("Install door frames and hardware"));
    // Exactly one visible occurrence - the left-table row, not duplicated
    // inside a bar.
    expect(screen.getAllByText("Install door frames and hardware")).toHaveLength(1);
  });

  it("groups tasks by phase with a collapsible header shared by both panes", async () => {
    const todayIso = new Date().toISOString().slice(0, 10);
    taskExecutionApi.list.mockResolvedValue([
      task({ id: "t1", title: "Pour slab", phase: "Civil", planned_start_date: todayIso, planned_end_date: todayIso }),
    ]);
    render(<ExecutionCalendarView projectId="p1" user={admin}/>);
    const groupHeader = await screen.findByRole("button", { name: /civil \(1\)/i });
    expect(screen.getByText("Pour slab")).toBeInTheDocument();
    fireEvent.click(groupHeader);
    await waitFor(() => expect(screen.queryByText("Pour slab")).not.toBeInTheDocument());
    fireEvent.click(groupHeader);
    expect(await screen.findByText("Pour slab")).toBeInTheDocument();
  });

  // The whole point of this indicator: a user should be able to tell WHY a
  // task is blocked without opening the drawer, and tell "blocked by both"
  // apart from either single cause.
  describe("blocking-reason badges", () => {
    const blockedBy = kinds => ({
      readiness: {
        state: "blocked",
        reasons: kinds.map(kind => ({ kind, subject_id: `s-${kind}`, detail: `Waiting on ${kind}.`, blocking: true })),
        advisories: [],
      },
    });

    // A dated task renders twice - once as a TaskListRow (left table) and
    // once as a TaskBarRow (right grid) - so badge titles are asserted with
    // getAllByTitle/queryAllByTitle rather than the single-match getByTitle.
    it("shows only the dependency badge when blocked solely by a predecessor", async () => {
      taskExecutionApi.list.mockResolvedValue([task({ title: "Pour slab", ...blockedBy(["dependency"]) })]);
      render(<ExecutionCalendarView projectId="p1" user={admin}/>);
      await screen.findByText("Pour slab");
      expect(screen.getAllByTitle("Blocked by a dependent task").length).toBeGreaterThan(0);
      expect(screen.queryAllByTitle("Blocked by an external approval")).toHaveLength(0);
    });

    it("shows only the approval badge when blocked solely by an external approval", async () => {
      taskExecutionApi.list.mockResolvedValue([task({ title: "Pour slab", ...blockedBy(["approval"]) })]);
      render(<ExecutionCalendarView projectId="p1" user={admin}/>);
      await screen.findByText("Pour slab");
      expect(screen.getAllByTitle("Blocked by an external approval").length).toBeGreaterThan(0);
      expect(screen.queryAllByTitle("Blocked by a dependent task")).toHaveLength(0);
    });

    it("shows both badges when a task is blocked by both a dependency and an approval", async () => {
      taskExecutionApi.list.mockResolvedValue([task({ title: "Pour slab", ...blockedBy(["dependency", "approval"]) })]);
      render(<ExecutionCalendarView projectId="p1" user={admin}/>);
      await screen.findByText("Pour slab");
      expect(screen.getAllByTitle("Blocked by a dependent task").length).toBeGreaterThan(0);
      expect(screen.getAllByTitle("Blocked by an external approval").length).toBeGreaterThan(0);
    });

    it("shows no reason badge for a task that isn't blocked", async () => {
      taskExecutionApi.list.mockResolvedValue([task({ title: "Pour slab", readiness: { state: "ready", reasons: [], advisories: [] } })]);
      render(<ExecutionCalendarView projectId="p1" user={admin}/>);
      await screen.findByText("Pour slab");
      expect(screen.queryAllByTitle("Blocked by a dependent task")).toHaveLength(0);
      expect(screen.queryAllByTitle("Blocked by an external approval")).toHaveLength(0);
    });
  });

  it("resets search, phase, status and date-range filters on Reset", async () => {
    taskExecutionApi.list.mockResolvedValue([
      task({ id: "t1", title: "Pour slab" }),
      task({ id: "t2", title: "Fit ceiling" }),
    ]);
    render(<ExecutionCalendarView projectId="p1" user={admin}/>);
    await screen.findByText("Pour slab");
    fireEvent.change(screen.getByPlaceholderText(/search task code/i), { target: { value: "ceiling" } });
    await waitFor(() => expect(screen.queryByText("Pour slab")).not.toBeInTheDocument());
    fireEvent.change(screen.getByLabelText(/from date/i), { target: { value: "2026-01-01" } });
    fireEvent.click(screen.getByRole("button", { name: /reset/i }));
    expect(await screen.findByText("Pour slab")).toBeInTheDocument();
    expect(screen.getByPlaceholderText(/search task code/i)).toHaveValue("");
    expect(screen.getByLabelText(/from date/i)).toHaveValue("");
  });

  it("excludes a dated task whose planned range falls outside the selected date range", async () => {
    taskExecutionApi.list.mockResolvedValue([
      task({ id: "t1", title: "Pour slab", planned_start_date: "2026-08-01", planned_end_date: "2026-08-02" }),
      task({ id: "t2", title: "Fit ceiling", planned_start_date: "2026-09-15", planned_end_date: "2026-09-16" }),
    ]);
    render(<ExecutionCalendarView projectId="p1" user={admin}/>);
    await screen.findByText("Pour slab");
    fireEvent.change(screen.getByLabelText(/from date/i), { target: { value: "2026-09-01" } });
    await waitFor(() => expect(screen.queryByText("Pour slab")).not.toBeInTheDocument());
    expect(screen.getByText("Fit ceiling")).toBeInTheDocument();
  });

  it("offers Week/Month/Full zoom presets, defaulting to Month", async () => {
    const todayIso = new Date().toISOString().slice(0, 10);
    taskExecutionApi.list.mockResolvedValue([task({ title: "Pour slab", planned_start_date: todayIso, planned_end_date: todayIso })]);
    render(<ExecutionCalendarView projectId="p1" user={admin}/>);
    await screen.findByText("Pour slab");
    expect(screen.getByRole("button", { name: "Month" })).toHaveAttribute("aria-pressed", "true");
    fireEvent.click(screen.getByRole("button", { name: "Week" }));
    expect(screen.getByRole("button", { name: "Week" })).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByRole("button", { name: "Month" })).toHaveAttribute("aria-pressed", "false");
  });

  it("scrolls the date grid when Previous/Next/Today are clicked", async () => {
    const todayIso = new Date().toISOString().slice(0, 10);
    taskExecutionApi.list.mockResolvedValue([task({ title: "Pour slab", planned_start_date: todayIso, planned_end_date: todayIso })]);
    render(<ExecutionCalendarView projectId="p1" user={admin}/>);
    await screen.findByText("Pour slab");
    const scrollBySpy = vi.fn();
    const scrollToSpy = vi.fn();
    // jsdom implements neither scrollBy nor scrollTo on elements - stub them
    // so the click handlers (real navigation, not fake data) can be observed.
    Element.prototype.scrollBy = scrollBySpy;
    Element.prototype.scrollTo = scrollToSpy;
    fireEvent.click(screen.getByRole("button", { name: /scroll forward a week/i }));
    expect(scrollBySpy).toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: /^today$/i }));
    expect(scrollToSpy).toHaveBeenCalled();
  });
});
