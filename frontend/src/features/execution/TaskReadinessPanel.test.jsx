import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { TaskReadinessPanel } from "./components/TaskReadinessPanel";

// U18: this panel renders what U12 computed and U15 shipped. The assertions
// below deliberately check that the ENGINE'S OWN sentence reaches the screen
// verbatim - if the panel ever starts recomposing reasons from `kind` and
// `subject_id`, the board and the engine would describe the same fact in two
// different vocabularies and these tests would catch it.

const reason = (extra = {}) => ({
  kind: "dependency", subject_id: "00000000-0000-0000-0000-000000000001",
  detail: "Waiting on T001 Mobilise site (planned).", blocking: true, ...extra,
});
const withReadiness = readiness => ({ id: "t1", original_code: "T001", title: "Fit ceiling", readiness });

describe("TaskReadinessPanel", () => {
  it("renders nothing for a task whose payload carries no readiness", () => {
    const { container } = render(<TaskReadinessPanel task={{ id: "t1" }}/>);
    expect(container).toBeEmptyDOMElement();
  });

  it("shows a ready state with no reasons", () => {
    render(<TaskReadinessPanel task={withReadiness({ state: "ready", reasons: [], advisories: [] })}/>);
    expect(screen.getByText("Ready to start")).toBeInTheDocument();
    expect(screen.queryByText(/things are holding this task/i)).not.toBeInTheDocument();
  });

  it("lists every blocking reason, not just the first", () => {
    render(<TaskReadinessPanel task={withReadiness({
      state: "blocked",
      reasons: [
        reason({ detail: "Waiting on T001 Mobilise site (planned)." }),
        reason({ subject_id: "id-2", detail: "Waiting on T002 Survey boundary (in progress)." }),
        reason({ kind: "approval", subject_id: "id-3", detail: "Waiting on external approval FIRE-NOC (pending)." }),
      ],
      advisories: [],
    })}/>);
    expect(screen.getByText("Blocked")).toBeInTheDocument();
    expect(screen.getByText("3 things are holding this task:")).toBeInTheDocument();
    expect(screen.getByText("Waiting on T001 Mobilise site (planned).")).toBeInTheDocument();
    expect(screen.getByText("Waiting on T002 Survey boundary (in progress).")).toBeInTheDocument();
    expect(screen.getByText("Waiting on external approval FIRE-NOC (pending).")).toBeInTheDocument();
  });

  it("names the specific predecessor a dependency reason points at", () => {
    render(<TaskReadinessPanel task={withReadiness({
      state: "blocked", reasons: [reason({ detail: "Waiting on T007 Electrical rough-in (planned)." })], advisories: [],
    })}/>);
    expect(screen.getByText(/T007 Electrical rough-in/)).toBeInTheDocument();
  });

  it("names the specific approval an approval reason points at", () => {
    render(<TaskReadinessPanel task={withReadiness({
      state: "blocked",
      reasons: [reason({ kind: "approval", detail: "Waiting on external approval FIRE-NOC (pending)." })],
      advisories: [],
    })}/>);
    expect(screen.getByText(/external approval FIRE-NOC/)).toBeInTheDocument();
  });

  // An unsatisfied fact a PM deliberately marked non-blocking. Reporting it
  // as a blocker would override their decision, so it must not change the
  // state or appear in the blocking list.
  it("keeps advisories out of the blocking list and behind a disclosure", () => {
    render(<TaskReadinessPanel task={withReadiness({
      state: "ready",
      reasons: [],
      advisories: [reason({ blocking: false, detail: "T009 Signage (planned) is unsatisfied but marked non-blocking." })],
    })}/>);
    expect(screen.getByText("Ready to start")).toBeInTheDocument();
    expect(screen.queryByText(/things are holding this task/i)).not.toBeInTheDocument();
    fireEvent.click(screen.getByText(/1 advisory note/i));
    expect(screen.getByText("T009 Signage (planned) is unsatisfied but marked non-blocking.")).toBeInTheDocument();
  });

  it("explains a blocked state that has no dependency or approval behind it", () => {
    render(<TaskReadinessPanel task={withReadiness({ state: "blocked", reasons: [], advisories: [] })}/>);
    expect(screen.getByText(/blocked by its lifecycle state/i)).toBeInTheDocument();
  });

  // R5/KTD1: readiness is advisory this release. The panel must say so, since
  // it can legitimately disagree with the controls sitting next to it.
  it("states that readiness is advisory", () => {
    render(<TaskReadinessPanel task={withReadiness({ state: "blocked", reasons: [reason()], advisories: [] })}/>);
    expect(screen.getByText(/advisory/i)).toBeInTheDocument();
  });

  it("labels each of the non-computed states rather than showing a raw value", () => {
    for (const [state, label] of [
      ["in_progress", "In progress"],
      ["awaiting_verification", "Awaiting verification"],
      ["awaiting_approval", "Awaiting approval"],
      ["completed", "Completed"],
      ["cancelled", "Cancelled"],
    ]) {
      const { unmount } = render(<TaskReadinessPanel task={withReadiness({ state, reasons: [], advisories: [] })}/>);
      expect(screen.getByText(label)).toBeInTheDocument();
      unmount();
    }
  });
});
