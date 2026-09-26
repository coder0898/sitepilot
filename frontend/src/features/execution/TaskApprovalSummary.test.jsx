import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { TaskApprovalSummary } from "./components/TaskApprovalSummary";

const approval = overrides => ({
  task_kind: "work", task_class: "standard", verification_required: true, approval_required: false,
  verifier_role: "site_supervisor", approver_role: null, approval_summary: "supervisor_verification",
  approval_status: "not_started", blocks_dependents_until_approved: false,
  ...overrides,
});

describe("TaskApprovalSummary type pill", () => {
  it("shows Standard for standard work", () => {
    render(<TaskApprovalSummary task={{ approval: approval() }}/>);
    expect(screen.getByText("Standard")).toBeInTheDocument();
  });

  it("shows Class A for class_a work", () => {
    render(<TaskApprovalSummary task={{ approval: approval({ task_class: "class_a", approval_summary: "supervisor_and_pm" }) }}/>);
    expect(screen.getByText("Class A")).toBeInTheDocument();
  });

  it("shows Approval Gate for an approval gate, never the class_a class templates give it", () => {
    render(<TaskApprovalSummary task={{ approval: approval({
      task_kind: "approval_gate", task_class: "class_a", verification_required: false, approval_required: true,
      approval_summary: "pm_approval",
    }) }}/>);
    expect(screen.getByText("Approval Gate")).toBeInTheDocument();
    expect(screen.queryByText("Class A")).not.toBeInTheDocument();
  });
});
