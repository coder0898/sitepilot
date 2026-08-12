import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { TaskReadinessPanel } from "./components/TaskReadinessPanel";

function reason(overrides = {}) {
  return {
    kind: "predecessor", code: "T001", title: "Task T001",
    detail: "T001 Task T001 must be finished first (currently in_progress).",
    status: "in_progress", enforced: true, ...overrides,
  };
}

function item(overrides = {}) {
  return {
    task_id: "t1", original_code: "T002", title: "Task T002", lifecycle_status: "planned",
    state: "blocked", startable: false, reasons: [], guard_diverges: false, ...overrides,
  };
}

function readiness(overrides = {}) {
  return { project_id: "p1", total: 1, startable_count: 0, items: [], unresolved_gates: [], ...overrides };
}

describe("TaskReadinessPanel", () => {
  it("lists startable work", () => {
    render(<TaskReadinessPanel readiness={readiness({
      startable_count: 1, items: [item({ startable: true, state: "ready", original_code: "T001" })],
    })}/>);
    expect(screen.getByText("Ready to start (1)")).toBeInTheDocument();
    expect(screen.getByText("T001")).toBeInTheDocument();
    expect(screen.getByText("Can start")).toBeInTheDocument();
  });

  it("names every blocking predecessor and gate on a blocked task", () => {
    render(<TaskReadinessPanel readiness={readiness({
      items: [item({ reasons: [
        reason(),
        reason({ kind: "gate", code: "E001", title: "Landlord approval", detail: "E001 Landlord approval is pending_review.", status: "pending_review" }),
      ] })],
    })}/>);
    expect(screen.getByText(/T001 Task T001 must be finished first/)).toBeInTheDocument();
    expect(screen.getByText(/E001 Landlord approval is pending_review/)).toBeInTheDocument();
  });

  it("renders an empty state rather than a bare heading when nothing can start", () => {
    render(<TaskReadinessPanel readiness={readiness({ items: [item({ reasons: [reason()] })] })}/>);
    expect(screen.getByText("Nothing can start right now")).toBeInTheDocument();
  });

  it("says the overlap rule is not enforced when readiness diverges from the guard", () => {
    // Covers AE7. The panel must not appear to contradict the board, which
    // will still refuse the start.
    render(<TaskReadinessPanel readiness={readiness({
      startable_count: 1, items: [item({ startable: true, state: "ready", guard_diverges: true })],
    })}/>);
    expect(screen.getByText("Overlap not yet enforced")).toBeInTheDocument();
    expect(screen.getByText(/still\s+asks for that predecessor to be finished/)).toBeInTheDocument();
  });

  it("marks an advisory reason as advisory", () => {
    render(<TaskReadinessPanel readiness={readiness({
      startable_count: 1,
      items: [item({ startable: true, reasons: [reason({
        kind: "excluded_predecessor", enforced: false,
        detail: "T079 was excluded from this project's scope, and the work it would have depended on has not been carried across. Not enforced.",
      })] })],
    })}/>);
    expect(screen.getByText("Advisory")).toBeInTheDocument();
  });

  it("surfaces gates that cover no task", () => {
    render(<TaskReadinessPanel readiness={readiness({ unresolved_gates: [reason({
      kind: "unresolved_gate", code: "E005", title: "Relevant procurement tasks", enforced: false,
      detail: "Relevant procurement tasks covers no task on this project, so approving it releases nothing. Its coverage has not been configured.",
    })] })}/>);
    expect(screen.getByText("Approvals that cover no task")).toBeInTheDocument();
    expect(screen.getByText(/releases nothing/)).toBeInTheDocument();
  });

  it("surfaces a failed fetch without blanking the tab", () => {
    render(<TaskReadinessPanel readiness={null} error="Readiness could not be worked out for this project."/>);
    expect(screen.getByText("Readiness could not be worked out for this project.")).toBeInTheDocument();
  });

  it("renders nothing at all when there is no readiness and no error", () => {
    const { container } = render(<TaskReadinessPanel readiness={null}/>);
    expect(container).toBeEmptyDOMElement();
  });
});
