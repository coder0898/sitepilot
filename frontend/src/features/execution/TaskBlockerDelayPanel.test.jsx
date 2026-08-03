import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { taskExecutionApi } from "../../api/taskExecutionApi";
import { TaskBlockerDelayPanel } from "./components/TaskBlockerDelayPanel";

vi.mock("../../api/taskExecutionApi", () => ({ taskExecutionApi: {
  logBlocker: vi.fn(), resolveBlocker: vi.fn(), logDelay: vi.fn(),
} }));

const task = { id: "t1", blockers: [], delays: [] };

beforeEach(() => {
  vi.clearAllMocks();
});

describe("TaskBlockerDelayPanel", () => {
  it("logs a blocker and clears the form", async () => {
    taskExecutionApi.logBlocker.mockResolvedValue({});
    const onChanged = vi.fn();
    render(<TaskBlockerDelayPanel projectId="p1" task={task} onChanged={onChanged}/>);
    expect(screen.getByText("No blockers logged.")).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("Type"), { target: { value: "material" } });
    fireEvent.change(screen.getByLabelText("Description"), { target: { value: "Waiting on cement delivery." } });
    fireEvent.click(screen.getByRole("button", { name: /log blocker/i }));
    await waitFor(() => expect(taskExecutionApi.logBlocker).toHaveBeenCalledWith("p1", "t1", { type: "material", description: "Waiting on cement delivery." }));
    await waitFor(() => expect(onChanged).toHaveBeenCalledTimes(1));
    expect(screen.getByLabelText("Type")).toHaveValue("");
  });

  it("resolves an open blocker", async () => {
    taskExecutionApi.resolveBlocker.mockResolvedValue({});
    const onChanged = vi.fn();
    const withBlocker = { ...task, blockers: [{ id: "b1", type: "material", description: "Waiting on cement.", resolved_at: null }] };
    render(<TaskBlockerDelayPanel projectId="p1" task={withBlocker} onChanged={onChanged}/>);
    expect(screen.getByText("Open")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Resolve" }));
    await waitFor(() => expect(taskExecutionApi.resolveBlocker).toHaveBeenCalledWith("p1", "t1", "b1"));
    expect(onChanged).toHaveBeenCalledTimes(1);
  });

  it("does not show Resolve for an already-resolved blocker", () => {
    const withBlocker = { ...task, blockers: [{ id: "b1", type: "material", description: "Waiting on cement.", resolved_at: "2026-08-02T00:00:00Z" }] };
    render(<TaskBlockerDelayPanel projectId="p1" task={withBlocker} onChanged={vi.fn()}/>);
    expect(screen.getByText("Resolved")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Resolve" })).not.toBeInTheDocument();
  });

  it("shows the vendor id field only when responsibility is vendor, and requires it", async () => {
    taskExecutionApi.logDelay.mockResolvedValue({});
    render(<TaskBlockerDelayPanel projectId="p1" task={task} onChanged={vi.fn()}/>);
    expect(screen.getByLabelText(/vendor id/i)).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("Reason"), { target: { value: "Cement delayed at source." } });
    expect(screen.getByRole("button", { name: /log delay/i })).toBeDisabled();
    fireEvent.change(screen.getByLabelText(/vendor id/i), { target: { value: "3fa85f64-5717-4562-b3fc-2c963f66afa6" } });
    fireEvent.click(screen.getByRole("button", { name: /log delay/i }));
    await waitFor(() => expect(taskExecutionApi.logDelay).toHaveBeenCalledWith("p1", "t1", { responsibility_type: "vendor", responsible_vendor_id: "3fa85f64-5717-4562-b3fc-2c963f66afa6", reason: "Cement delayed at source.", impact_days: 1 }));

    fireEvent.change(screen.getByLabelText("Responsibility"), { target: { value: "client" } });
    expect(screen.queryByLabelText("Vendor ID")).not.toBeInTheDocument();
  });

  it("rejects a non-UUID vendor id before submitting", async () => {
    render(<TaskBlockerDelayPanel projectId="p1" task={task} onChanged={vi.fn()}/>);
    fireEvent.change(screen.getByLabelText("Reason"), { target: { value: "Cement delayed at source." } });
    fireEvent.change(screen.getByLabelText(/vendor id/i), { target: { value: "vendor-123" } });
    expect(screen.getByRole("button", { name: /log delay/i })).toBeDisabled();
    expect(screen.getByText("Must be a valid UUID.")).toBeInTheDocument();
    expect(taskExecutionApi.logDelay).not.toHaveBeenCalled();
  });

  it("submits a non-vendor delay without a vendor id", async () => {
    taskExecutionApi.logDelay.mockResolvedValue({});
    render(<TaskBlockerDelayPanel projectId="p1" task={task} onChanged={vi.fn()}/>);
    fireEvent.change(screen.getByLabelText("Responsibility"), { target: { value: "client" } });
    fireEvent.change(screen.getByLabelText("Reason"), { target: { value: "Client decision pending." } });
    fireEvent.change(screen.getByLabelText("Impact (days)"), { target: { value: "3" } });
    fireEvent.click(screen.getByRole("button", { name: /log delay/i }));
    await waitFor(() => expect(taskExecutionApi.logDelay).toHaveBeenCalledWith("p1", "t1", { responsibility_type: "client", responsible_vendor_id: null, reason: "Client decision pending.", impact_days: 3 }));
  });
});
