import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { TaskLifecycleStepper } from "./components/TaskLifecycleStepper";

describe("TaskLifecycleStepper", () => {
  it("shows Review and Approved for a task that requires PM/Admin approval", () => {
    render(<TaskLifecycleStepper status="verified" approvalRequired={true}/>);
    expect(screen.getByText("Review")).toBeInTheDocument();
    expect(screen.getByText("Approved")).toBeInTheDocument();
  });

  it("collapses Review/Approved into a single Completed step when no approval is required", () => {
    render(<TaskLifecycleStepper status="submitted" approvalRequired={false}/>);
    expect(screen.queryByText("Review")).not.toBeInTheDocument();
    expect(screen.queryByText("Approved")).not.toBeInTheDocument();
    expect(screen.getByText("Completed")).toBeInTheDocument();
  });

  it("marks Completed as the current step once a no-approval task is done", () => {
    render(<TaskLifecycleStepper status="completed" approvalRequired={false}/>);
    expect(screen.getByText("Completed")).toBeInTheDocument();
    expect(screen.queryByText("Review")).not.toBeInTheDocument();
  });

  it("defaults to the full stepper when approvalRequired is unknown", () => {
    render(<TaskLifecycleStepper status="verified"/>);
    expect(screen.getByText("Review")).toBeInTheDocument();
  });

  it("shows Cancelled instead of the stepper for a cancelled task", () => {
    render(<TaskLifecycleStepper status="cancelled" approvalRequired={false}/>);
    expect(screen.getByText("Cancelled")).toBeInTheDocument();
    expect(screen.queryByText("Completed")).not.toBeInTheDocument();
  });

  it("shows the rejected branch without approval steps for a no-approval task", () => {
    render(<TaskLifecycleStepper status="rejected" approvalRequired={false}/>);
    expect(screen.getByText(/rejected/i)).toBeInTheDocument();
    expect(screen.queryByText("Review")).not.toBeInTheDocument();
  });
});
