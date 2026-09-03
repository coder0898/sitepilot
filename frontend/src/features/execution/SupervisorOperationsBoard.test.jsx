import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { projectsApi } from "../../api/projectsApi";
import { taskExecutionApi } from "../../api/taskExecutionApi";
import { SupervisorOperationsBoard } from "./components/SupervisorOperationsBoard";

vi.mock("../../api/projectsApi", () => ({ projectsApi: { detail: vi.fn() } }));
vi.mock("../../api/taskExecutionApi", () => ({ taskExecutionApi: { list: vi.fn(), detail: vi.fn(), listExternalApprovals: vi.fn() } }));

const supervisor = { id: "u-sup", role: "supervisor" };

const isoOffsetDays = days => {
  const date = new Date();
  date.setUTCDate(date.getUTCDate() + days);
  return date.toISOString().slice(0, 10);
};

const task = (overrides = {}) => ({
  id: "t1", project_id: "p1", baseline_id: "b1", original_code: "T001", template_sequence: 1,
  title: "Install gypsum partition", task_kind: "work", task_class: "standard", lifecycle_status: "in_progress",
  schedule_classification: "execution", planned_start_day: 1, planned_end_day: 1,
  planned_start_date: isoOffsetDays(0), planned_end_date: isoOffsetDays(0),
  phase: "Interiors", category: "Civil", evidence_required: false, open_blocker_count: 0, active_support_count: 0,
  readiness: { state: "in_progress", reasons: [], advisories: [] }, variance: null,
  created_at: "2026-08-01T00:00:00Z", updated_at: "2026-08-01T00:00:00Z",
  ...overrides,
});

beforeEach(() => {
  vi.clearAllMocks();
  projectsApi.detail.mockResolvedValue({ id: "p1", memberships: [] });
  taskExecutionApi.listExternalApprovals.mockResolvedValue([]);
});

describe("SupervisorOperationsBoard", () => {
  it("buckets a task into Today when its planned range covers today, and not into Tomorrow", async () => {
    taskExecutionApi.list.mockResolvedValue([task({ title: "Install gypsum partition" })]);
    render(<SupervisorOperationsBoard projectId="p1" user={supervisor}/>);
    expect(await screen.findByText("3-Day Operations Board")).toBeInTheDocument();
    const [, todayColumn, tomorrowColumn] = screen.getAllByRole("article");
    expect(within(todayColumn).getByText("Install gypsum partition")).toBeInTheDocument();
    expect(within(tomorrowColumn).queryByText("Install gypsum partition")).not.toBeInTheDocument();
  });

  it("buckets a task into Tomorrow only, when planned to start tomorrow", async () => {
    taskExecutionApi.list.mockResolvedValue([task({
      title: "Electrical wiring first fix",
      planned_start_date: isoOffsetDays(1), planned_end_date: isoOffsetDays(1),
    })]);
    render(<SupervisorOperationsBoard projectId="p1" user={supervisor}/>);
    const [yesterdayColumn, todayColumn, tomorrowColumn] = await screen.findAllByRole("article");
    expect(within(tomorrowColumn).getByText("Electrical wiring first fix")).toBeInTheDocument();
    expect(within(todayColumn).queryByText("Electrical wiring first fix")).not.toBeInTheDocument();
    expect(within(yesterdayColumn).queryByText("Electrical wiring first fix")).not.toBeInTheDocument();
  });

  it("carries an unfinished task overdue since yesterday into Today, flagged as delayed", async () => {
    taskExecutionApi.list.mockResolvedValue([task({
      title: "Rebar fixing",
      planned_start_date: isoOffsetDays(-1), planned_end_date: isoOffsetDays(-1),
      lifecycle_status: "in_progress",
      variance: { status: "late", days: 1, measured_against: "today" },
    })]);
    render(<SupervisorOperationsBoard projectId="p1" user={supervisor}/>);
    const [yesterdayColumn, todayColumn] = await screen.findAllByRole("article");
    expect(within(todayColumn).getByText("Rebar fixing")).toBeInTheDocument();
    expect(within(todayColumn).getByText("1d late")).toBeInTheDocument();
    expect(within(yesterdayColumn).getByText("Rebar fixing")).toBeInTheDocument();
  });

  it("does not carry a completed task forward past the day it actually finished", async () => {
    taskExecutionApi.list.mockResolvedValue([task({
      title: "Formwork removal",
      planned_start_date: isoOffsetDays(-2), planned_end_date: isoOffsetDays(-2),
      lifecycle_status: "completed",
      actual_start_at: `${isoOffsetDays(-2)}T09:00:00Z`, actual_finish_at: `${isoOffsetDays(-2)}T17:00:00Z`,
    })]);
    render(<SupervisorOperationsBoard projectId="p1" user={supervisor}/>);
    await screen.findByText("3-Day Operations Board");
    const [, todayColumn] = screen.getAllByRole("article");
    expect(within(todayColumn).queryByText("Formwork removal")).not.toBeInTheDocument();
  });

  it("shows a task started before its planned date under Today, flagged as early", async () => {
    taskExecutionApi.list.mockResolvedValue([task({
      title: "Plumbing rough-in",
      planned_start_date: isoOffsetDays(2), planned_end_date: isoOffsetDays(3),
      lifecycle_status: "in_progress",
      actual_start_at: `${isoOffsetDays(0)}T08:00:00Z`,
    })]);
    render(<SupervisorOperationsBoard projectId="p1" user={supervisor}/>);
    const [, todayColumn] = await screen.findAllByRole("article");
    expect(within(todayColumn).getByText("Plumbing rough-in")).toBeInTheDocument();
    expect(within(todayColumn).getByText("2d early")).toBeInTheDocument();
  });

  it("sorts delayed and early-started tasks ahead of routine tasks in the same column", async () => {
    taskExecutionApi.list.mockResolvedValue([
      task({ id: "t-routine", title: "Routine task" }),
      task({
        id: "t-late", title: "Overdue task",
        planned_start_date: isoOffsetDays(-1), planned_end_date: isoOffsetDays(-1),
        variance: { status: "late", days: 1, measured_against: "today" },
      }),
    ]);
    render(<SupervisorOperationsBoard projectId="p1" user={supervisor}/>);
    const [, todayColumn] = await screen.findAllByRole("article");
    const titles = within(todayColumn).getAllByRole("button").map(button => button.textContent);
    expect(titles.findIndex(text => text.includes("Overdue task"))).toBeLessThan(
      titles.findIndex(text => text.includes("Routine task")),
    );
  });

  it("counts a blocked task under Attention Required and can filter to it", async () => {
    taskExecutionApi.list.mockResolvedValue([
      task({ id: "t1", title: "Install gypsum partition", readiness: { state: "blocked", reasons: [], advisories: [] } }),
      task({ id: "t2", title: "Paint base coat", readiness: { state: "in_progress", reasons: [], advisories: [] } }),
    ]);
    render(<SupervisorOperationsBoard projectId="p1" user={supervisor}/>);
    await screen.findByText("Install gypsum partition");
    const attention = screen.getByRole("region", { name: /attention required/i });
    const blockedButton = within(attention).getByRole("button", { name: /1 Blocked/i });
    expect(blockedButton).toBeInTheDocument();
    fireEvent.click(blockedButton);
    await waitFor(() => expect(screen.queryByText("Paint base coat")).not.toBeInTheDocument());
    expect(screen.getByText("Install gypsum partition")).toBeInTheDocument();
  });

  it("opens the task detail drawer when a card is clicked", async () => {
    taskExecutionApi.list.mockResolvedValue([task({ title: "Install gypsum partition" })]);
    taskExecutionApi.detail.mockResolvedValue({
      ...task({ title: "Install gypsum partition" }), description: "Frame and board the partition.",
      predecessors: [], progress_updates: [], verifications: [], approvals: [],
      blockers: [], delays: [], support_assignments: [], audit_events: [],
    });
    render(<SupervisorOperationsBoard projectId="p1" user={supervisor}/>);
    fireEvent.click(await screen.findByText("Install gypsum partition"));
    expect(await screen.findByText("Frame and board the partition.")).toBeInTheDocument();
  });

  it("shows an empty state when the project has no execution tasks", async () => {
    taskExecutionApi.list.mockResolvedValue([]);
    render(<SupervisorOperationsBoard projectId="p1" user={supervisor}/>);
    expect(await screen.findByText("No execution tasks yet")).toBeInTheDocument();
  });
});
