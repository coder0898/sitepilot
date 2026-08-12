import { useEffect, useMemo, useState } from "react";
import { EmptyState } from "../../../components/ui";
import { ScheduleTaskCards } from "./ScheduleTaskCards";
import { buildTimelineRows, columnSpan, timelineDayCount } from "./scheduleTimelineModel";

// U12: baseline against actual, across the project's days.
//
// A rebuild, not a port. The approved demo emits one absolutely positioned
// element per day cell and rebuilds roughly 4,200 nodes through innerHTML
// on every state change. Here each task contributes at most two positioned
// bars spanning their own columns, so a 99-task project is a couple of
// hundred nodes and React can keep them.
//
// Desktop and mobile are chosen in JavaScript, not with a CSS media query,
// so only one of the two trees is ever built. The demo builds both and
// hides one, which costs the work twice on the device least able to afford
// it.

const DAY_COLUMN_PX = 28;
const DESKTOP_QUERY = "(min-width: 1024px)";

function useIsDesktop() {
  const [isDesktop, setIsDesktop] = useState(
    () => typeof window !== "undefined" && window.matchMedia?.(DESKTOP_QUERY).matches,
  );
  useEffect(() => {
    const query = window.matchMedia?.(DESKTOP_QUERY);
    if (!query) return undefined;
    const sync = event => setIsDesktop(event.matches);
    query.addEventListener("change", sync);
    setIsDesktop(query.matches);
    return () => query.removeEventListener("change", sync);
  }, []);
  return isDesktop;
}

function Bar({ from, to, className, title }) {
  if (from == null) return null;
  return <div
    className={`h-2.5 self-center rounded-full ${className}`}
    style={{ gridColumn: columnSpan(from, to) }}
    title={title}
  />;
}

function TimelineRow({ row, dayCount }) {
  return <>
    <div className="sticky left-0 z-10 flex min-w-0 items-center gap-2 bg-white pr-3">
      <span className="shrink-0 text-[11px] font-black text-blue-700">{row.code}</span>
      <span className="truncate text-xs text-slate-700" title={row.title}>{row.title}</span>
    </div>
    <div
      className="grid items-center gap-y-1 py-1"
      style={{ gridTemplateColumns: `repeat(${dayCount}, ${DAY_COLUMN_PX}px)`, gridAutoRows: "10px" }}
    >
      <Bar
        from={row.baselineStart} to={row.baselineEnd}
        className="bg-slate-300"
        title={`Baseline: day ${row.baselineStart} to ${row.baselineEnd}`}
      />
      <Bar
        from={row.actualStart} to={row.actualEnd}
        className={row.isEarly ? "bg-violet-500" : "bg-blue-600"}
        title={row.actualStart == null ? undefined
          : `Actual: day ${row.actualStart} to ${row.actualEnd}${row.isUnfinished ? " (still running)" : ""}`}
      />
    </div>
  </>;
}

export function ScheduleTimeline({ tasks, startDate }) {
  const isDesktop = useIsDesktop();
  const rows = useMemo(() => buildTimelineRows(tasks, startDate), [tasks, startDate]);
  const dayCount = useMemo(() => timelineDayCount(rows), [rows]);

  if (!rows.length) {
    return <EmptyState
      title="Nothing to plot yet"
      description="Tasks appear here once the project is activated and its schedule dates are derived."
    />;
  }

  return <div className="grid gap-3 rounded-2xl border border-slate-200 bg-white p-5">
    <div className="flex flex-wrap items-center justify-between gap-3">
      <div>
        <h3 className="m-0 font-serif text-lg text-slate-950">Baseline against actual</h3>
        <p className="mt-1 text-sm text-slate-500">{rows.length} scheduled tasks across {dayCount} days.</p>
      </div>
      {/* The legend explains bar colours, so it only belongs where there
          are bars - the mobile cards say it in words instead. */}
      {isDesktop && <div className="flex flex-wrap items-center gap-3 text-xs text-slate-600">
        <span className="flex items-center gap-1.5"><i className="h-2.5 w-6 rounded-full bg-slate-300"/> Baseline</span>
        <span className="flex items-center gap-1.5"><i className="h-2.5 w-6 rounded-full bg-blue-600"/> Actual</span>
        <span className="flex items-center gap-1.5"><i className="h-2.5 w-6 rounded-full bg-violet-500"/> Started early</span>
      </div>}
    </div>

    {isDesktop ? (
      <div className="overflow-x-auto">
        <div className="grid min-w-max" style={{ gridTemplateColumns: "minmax(200px, 240px) max-content" }}>
          {rows.map(row => <TimelineRow key={row.id} row={row} dayCount={dayCount}/>)}
        </div>
      </div>
    ) : (
      <ScheduleTaskCards rows={rows}/>
    )}
  </div>;
}
