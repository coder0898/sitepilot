import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ScheduleTimeline } from "./components/ScheduleTimeline";
import { buildTimelineRows, columnSpan, dayIndexOf, timelineDayCount } from "./components/scheduleTimelineModel";

const START = "2026-08-01";

function task(overrides = {}) {
  return {
    id: "t1", original_code: "T005", title: "Task T005", phase: "Fit-out", lifecycle_status: "in_progress",
    planned_start_day: 5, planned_end_day: 8,
    actual_start_at: null, actual_finish_at: null, early_start_reason: null, ...overrides,
  };
}

function setViewport(isDesktop) {
  window.matchMedia = vi.fn().mockReturnValue({
    matches: isDesktop, addEventListener: vi.fn(), removeEventListener: vi.fn(),
  });
}

beforeEach(() => { vi.clearAllMocks(); setViewport(true); });

describe("timeline arithmetic", () => {
  it("treats day 1 as the project start date itself", () => {
    expect(dayIndexOf(START, "2026-08-01T09:00:00Z")).toBe(1);
    expect(dayIndexOf(START, "2026-08-08T23:00:00Z")).toBe(8);
  });

  it("spans a task's own columns inclusively", () => {
    // Days 5 to 8 is four columns, so the half-open range ends at 9.
    expect(columnSpan(5, 8)).toBe("5 / 9");
    expect(columnSpan(3, 3)).toBe("3 / 4");
  });

  it("runs an unfinished task's actual bar to today, not to its baseline end", () => {
    const [row] = buildTimelineRows(
      [task({ actual_start_at: "2026-08-05T08:00:00Z" })], START, new Date("2026-08-20T12:00:00Z"),
    );
    expect(row.actualStart).toBe(5);
    expect(row.actualEnd).toBe(20);
    expect(row.isUnfinished).toBe(true);
  });

  it("stops a finished task's bar at its actual finish", () => {
    const [row] = buildTimelineRows(
      [task({ actual_start_at: "2026-08-05T08:00:00Z", actual_finish_at: "2026-08-11T17:00:00Z" })],
      START, new Date("2026-09-30T12:00:00Z"),
    );
    expect(row.actualEnd).toBe(11);
    expect(row.isUnfinished).toBe(false);
  });

  it("gives a task that never started a baseline bar and no actual bar", () => {
    const [row] = buildTimelineRows([task()], START, new Date("2026-08-20T12:00:00Z"));
    expect(row.baselineStart).toBe(5);
    expect(row.actualStart).toBeNull();
    expect(row.actualEnd).toBeNull();
  });

  it("flags a task that started before its baseline", () => {
    const [row] = buildTimelineRows(
      [task({ actual_start_at: "2026-08-02T08:00:00Z", early_start_reason: "Crew arrived early." })],
      START, new Date("2026-08-20T12:00:00Z"),
    );
    expect(row.actualStart).toBe(2);
    expect(row.isEarly).toBe(true);
  });

  it("excludes a pre-activation task rather than drawing it at column zero", () => {
    const rows = buildTimelineRows(
      [task(), task({ id: "t0", original_code: "T000", planned_start_day: null, planned_end_day: null })],
      START, new Date("2026-08-20T12:00:00Z"),
    );
    expect(rows.map(row => row.code)).toEqual(["T005"]);
  });

  it("widens the grid to hold a bar that runs past the template's length", () => {
    const rows = buildTimelineRows(
      [task({ planned_start_day: 44, planned_end_day: 45, actual_start_at: "2026-09-14T08:00:00Z" })],
      START, new Date("2026-10-05T12:00:00Z"),
    );
    expect(timelineDayCount(rows)).toBe(66);
  });
});

describe("ScheduleTimeline", () => {
  it("renders a bar per task with its own column span", () => {
    const { container } = render(<ScheduleTimeline tasks={[task()]} startDate={START}/>);
    const bars = container.querySelectorAll('[style*="grid-column"]');
    expect(bars).toHaveLength(1);
    expect(bars[0].getAttribute("style")).toContain("5 / 9");
  });

  it("renders both bars once a task has started", () => {
    const { container } = render(
      <ScheduleTimeline tasks={[task({ actual_start_at: "2026-08-05T08:00:00Z" })]} startDate={START}/>,
    );
    expect(container.querySelectorAll('[style*="grid-column"]')).toHaveLength(2);
  });

  it("renders the mobile cards instead of the grid on a narrow viewport", () => {
    // Only one of the two trees is ever built - the demo builds both and
    // hides one, paying for the work twice on the weakest device.
    setViewport(false);
    const { container } = render(
      <ScheduleTimeline tasks={[task({ actual_start_at: "2026-08-02T08:00:00Z", early_start_reason: "Crew arrived early." })]} startDate={START}/>,
    );
    expect(container.querySelectorAll('[style*="grid-column"]')).toHaveLength(0);
    expect(screen.getByText("Started early")).toBeInTheDocument();
    expect(screen.getByText(/Baseline: day 5 to 8/)).toBeInTheDocument();
    expect(screen.getByText("Crew arrived early.")).toBeInTheDocument();
  });

  it("renders an empty state when nothing is schedulable", () => {
    render(<ScheduleTimeline tasks={[]} startDate={START}/>);
    expect(screen.getByText("Nothing to plot yet")).toBeInTheDocument();
  });

  it("renders a 99-task project without timing out", () => {
    const tasks = Array.from({ length: 99 }, (_, index) => task({
      id: `t${index}`, original_code: `T${String(index + 1).padStart(3, "0")}`,
      planned_start_day: (index % 45) + 1, planned_end_day: (index % 45) + 2,
      actual_start_at: index % 3 === 0 ? "2026-08-05T08:00:00Z" : null,
    }));
    const { container } = render(<ScheduleTimeline tasks={tasks} startDate={START}/>);
    expect(screen.getByText(/99 scheduled tasks/)).toBeInTheDocument();
    // 99 baseline bars plus one actual bar for every third task.
    expect(container.querySelectorAll('[style*="grid-column"]')).toHaveLength(99 + 33);
  });
});
