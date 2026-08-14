import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { ScheduleTimeline, timelineSpan } from "./components/ScheduleTimeline";

// U16: bars are positioned as percentages of the project's date span, so the
// assertions below check the computed left/width rather than pixels. Dates
// are anchored relative to today, because "still running" and "today is
// marked" are facts about now - a hardcoded window would drift out of range
// and quietly stop testing anything.
const iso = days => {
  const date = new Date();
  date.setUTCDate(date.getUTCDate() + days);
  return date.toISOString().slice(0, 10);
};
const at = (days, time = "09:00:00") => `${iso(days)}T${time}Z`;

const task = (id, extra = {}) => ({
  id, original_code: id.toUpperCase(), title: `Task ${id}`, phase: "Structure",
  lifecycle_status: "completed", planned_start_date: null, planned_end_date: null,
  actual_start_at: null, actual_finish_at: null, variance: null, ...extra,
});

// A 20-day window centred on today keeps every fixture inside one span.
const onTime = task("t1", {
  title: "Pour slab", planned_start_date: iso(-10), planned_end_date: iso(-6),
  actual_start_at: at(-10), actual_finish_at: at(-6),
  variance: { status: "on_time", variance_days: 0, days: 0, measured_against: "actual_finish" },
});
const early = task("t2", {
  title: "Site setup", planned_start_date: iso(-4), planned_end_date: iso(-1),
  actual_start_at: at(-8), actual_finish_at: at(-5),
  variance: { status: "early", variance_days: -4, days: 4, measured_against: "actual_finish" },
});
const late = task("t3", {
  title: "Fit ceiling", planned_start_date: iso(-6), planned_end_date: iso(-3),
  actual_start_at: at(-6), actual_finish_at: at(2),
  variance: { status: "late", variance_days: 5, days: 5, measured_against: "actual_finish" },
});
const running = task("t4", {
  title: "Glazing", phase: "Envelope", lifecycle_status: "in_progress",
  planned_start_date: iso(-2), planned_end_date: iso(6), actual_start_at: at(-2),
});
const notStarted = task("t5", {
  title: "Snagging", phase: "Envelope", lifecycle_status: "planned",
  planned_start_date: iso(4), planned_end_date: iso(8),
});

const pct = value => Number.parseFloat(value);
const bar = label => screen.getByLabelText(label);

describe("ScheduleTimeline", () => {
  it("renders an empty state rather than a broken axis when nothing is dated", () => {
    render(<ScheduleTimeline tasks={[task("t9"), task("t8")]}/>);
    expect(screen.getByText("No dated tasks yet")).toBeInTheDocument();
    expect(screen.queryByLabelText(/^Baseline for/)).not.toBeInTheDocument();
  });

  it("renders an empty state for no tasks at all", () => {
    render(<ScheduleTimeline tasks={[]}/>);
    expect(screen.getByText("No dated tasks yet")).toBeInTheDocument();
  });

  it("draws a baseline bar spanning the planned dates", () => {
    render(<ScheduleTimeline tasks={[onTime]}/>);
    const baseline = bar("Baseline for T1");
    // Only task in the span, so its baseline starts at the left edge and the
    // span runs from its planned start to today.
    expect(pct(baseline.style.left)).toBe(0);
    expect(pct(baseline.style.width)).toBeGreaterThan(0);
    expect(baseline).toHaveAttribute("title", expect.stringContaining("Planned"));
  });

  it("draws a second bar for a task with recorded actuals", () => {
    render(<ScheduleTimeline tasks={[onTime]}/>);
    expect(bar("Baseline for T1")).toBeInTheDocument();
    expect(bar("Actual for T1")).toBeInTheDocument();
  });

  it("draws only a baseline bar for a task that never started", () => {
    render(<ScheduleTimeline tasks={[notStarted]}/>);
    expect(bar("Baseline for T5")).toBeInTheDocument();
    expect(screen.queryByLabelText("Actual for T5")).not.toBeInTheDocument();
  });

  it("runs an in-flight task's actual bar to today", () => {
    render(<ScheduleTimeline tasks={[running]}/>);
    const actual = bar("Actual for T4");
    expect(actual).toHaveAttribute("title", expect.stringContaining("still running"));
    // Span here is planned start (-2) to planned end (+6) = 9 days. The
    // actual starts on day 0 of the span and runs to today, day 2 - three
    // days inclusive, so a third of the track.
    expect(pct(actual.style.left)).toBeCloseTo(0, 1);
    expect(pct(actual.style.width)).toBeCloseTo((3 / 9) * 100, 1);
  });

  // The signature this whole view exists to show.
  it("starts an early task's actual bar before its baseline bar", () => {
    render(<ScheduleTimeline tasks={[early]}/>);
    expect(pct(bar("Actual for T2").style.left)).toBeLessThan(pct(bar("Baseline for T2").style.left));
  });

  it("ends a late task's actual bar after its baseline bar", () => {
    render(<ScheduleTimeline tasks={[late]}/>);
    const baseline = bar("Baseline for T3");
    const actual = bar("Actual for T3");
    const rightEdge = element => pct(element.style.left) + pct(element.style.width);
    expect(rightEdge(actual)).toBeGreaterThan(rightEdge(baseline));
  });

  // The unit's verification: three tasks, three visibly different
  // relationships between the two bars.
  it("gives an early, a late and an on-time task three different bar relationships", () => {
    render(<ScheduleTimeline tasks={[onTime, early, late]}/>);
    const delta = code => pct(bar(`Actual for ${code}`).style.left) - pct(bar(`Baseline for ${code}`).style.left);
    expect(delta("T1")).toBeCloseTo(0, 1);
    expect(delta("T2")).toBeLessThan(0);
    const rightEdge = label => pct(bar(label).style.left) + pct(bar(label).style.width);
    expect(rightEdge("Actual for T3")).toBeGreaterThan(rightEdge("Baseline for T3"));
  });

  it("groups tasks by phase, in the order the phases arrive", () => {
    render(<ScheduleTimeline tasks={[onTime, running]}/>);
    const timeline = document.querySelector('[data-region="timeline"]');
    const phases = within(timeline).getAllByRole("heading", { level: 4 }).map(node => node.textContent);
    expect(phases).toEqual(["Structure", "Envelope"]);
  });

  it("files a task with no phase under Unphased", () => {
    render(<ScheduleTimeline tasks={[task("t7", { phase: null, planned_start_date: iso(0), planned_end_date: iso(1) })]}/>);
    expect(screen.getAllByText("Unphased").length).toBeGreaterThan(0);
  });

  it("marks today", () => {
    render(<ScheduleTimeline tasks={[onTime, running]}/>);
    expect(screen.getByLabelText("Today")).toBeInTheDocument();
  });

  // Both regions are rendered and CSS decides which is visible, following
  // ManagementTable's existing split. jsdom does not evaluate media queries,
  // so this asserts the structure that drives them.
  it("renders a card list for mobile alongside the desktop timeline", () => {
    render(<ScheduleTimeline tasks={[onTime]}/>);
    const timeline = document.querySelector('[data-region="timeline"]');
    const cards = document.querySelector('[data-region="cards"]');
    expect(timeline.className).toContain("hidden md:block");
    expect(cards.className).toContain("md:hidden");
    // The card carries the same two facts the two bars carry.
    expect(within(cards).getByText("Pour slab")).toBeInTheDocument();
    expect(within(cards).getByText("Planned")).toBeInTheDocument();
    expect(within(cards).getByText("Actual")).toBeInTheDocument();
    // ...and the timeline region carries the bars, not the cards.
    expect(within(cards).queryByLabelText("Baseline for T1")).not.toBeInTheDocument();
    expect(within(timeline).getByLabelText("Baseline for T1")).toBeInTheDocument();
  });

  it("shows the backend's variance verdict on the mobile cards rather than recomputing one", () => {
    render(<ScheduleTimeline tasks={[early, late]}/>);
    const cards = document.querySelector('[data-region="cards"]');
    expect(within(cards).getByText("4d early")).toBeInTheDocument();
    expect(within(cards).getByText("5d late")).toBeInTheDocument();
  });

  it("says a task is not started on its card when it has no actuals", () => {
    render(<ScheduleTimeline tasks={[notStarted]}/>);
    const cards = document.querySelector('[data-region="cards"]');
    expect(within(cards).getByText("Not started")).toBeInTheDocument();
  });
});

describe("timelineSpan", () => {
  const today = new Date(`${iso(0)}T00:00:00Z`);

  it("returns null when no task carries a date", () => {
    expect(timelineSpan([task("t1")], today)).toBeNull();
  });

  // The case the view exists for: a task that overran its baseline must not
  // draw off the end of the track.
  it("stretches to cover an actual finish beyond every planned date", () => {
    const span = timelineSpan([late], today);
    expect(span.end >= new Date(`${iso(2)}T00:00:00Z`)).toBe(true);
  });

  it("always includes today, so the marker has somewhere to sit", () => {
    const span = timelineSpan([task("t1", { planned_start_date: iso(-30), planned_end_date: iso(-25) })], today);
    expect(span.end >= today).toBe(true);
  });

  it("is one day wide for a single-day project rather than zero", () => {
    const span = timelineSpan([task("t1", { planned_start_date: iso(0), planned_end_date: iso(0) })], today);
    expect(span.days).toBe(1);
  });
});
