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
  it("hides both forms by default", () => {
    render(<TaskBlockerDelayPanel projectId="p1" task={task} onChanged={vi.fn()}/>);
    expect(screen.getByText("No open blockers")).toBeInTheDocument();
    expect(screen.getByText("No delays logged")).toBeInTheDocument();
    expect(screen.queryByLabelText("Type")).not.toBeInTheDocument();
    expect(screen.queryByLabelText("Reason")).not.toBeInTheDocument();
  });

  it("opens only the blocker form, logs it, and collapses again", async () => {
    taskExecutionApi.logBlocker.mockResolvedValue({});
    const onChanged = vi.fn();
    render(<TaskBlockerDelayPanel projectId="p1" task={task} onChanged={onChanged}/>);

    fireEvent.click(screen.getByRole("button", { name: /report blocker/i }));
    expect(screen.getByLabelText("Type")).toBeInTheDocument();
    expect(screen.queryByLabelText("Reason")).not.toBeInTheDocument();

    fireEvent.change(screen.getByLabelText("Type"), { target: { value: "material" } });
    fireEvent.change(screen.getByLabelText("Description"), { target: { value: "Waiting on cement delivery." } });
    fireEvent.click(screen.getByRole("button", { name: /log blocker/i }));
    await waitFor(() => expect(taskExecutionApi.logBlocker).toHaveBeenCalledWith("p1", "t1", { type: "material", description: "Waiting on cement delivery." }));
    await waitFor(() => expect(onChanged).toHaveBeenCalledTimes(1));
    await waitFor(() => expect(screen.queryByLabelText("Type")).not.toBeInTheDocument());
  });

  it("cancelling the blocker form collapses it without submitting", () => {
    render(<TaskBlockerDelayPanel projectId="p1" task={task} onChanged={vi.fn()}/>);
    fireEvent.click(screen.getByRole("button", { name: /report blocker/i }));
    expect(screen.getByLabelText("Type")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
    expect(screen.queryByLabelText("Type")).not.toBeInTheDocument();
    expect(taskExecutionApi.logBlocker).not.toHaveBeenCalled();
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

  it("shows the vendor id field only when responsibility is vendor", () => {
    render(<TaskBlockerDelayPanel projectId="p1" task={task} onChanged={vi.fn()}/>);
    fireEvent.click(screen.getByRole("button", { name: /report delay/i }));
    expect(screen.getByLabelText(/vendor id/i)).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("Responsibility"), { target: { value: "client" } });
    expect(screen.queryByLabelText("Vendor ID")).not.toBeInTheDocument();
  });

  it("requires the vendor id and submits a vendor delay, then collapses the form", async () => {
    taskExecutionApi.logDelay.mockResolvedValue({});
    render(<TaskBlockerDelayPanel projectId="p1" task={task} onChanged={vi.fn()}/>);
    fireEvent.click(screen.getByRole("button", { name: /report delay/i }));
    fireEvent.change(screen.getByLabelText("Reason"), { target: { value: "Cement delayed at source." } });
    expect(screen.getByRole("button", { name: /log delay/i })).toBeDisabled();
    fireEvent.change(screen.getByLabelText(/vendor id/i), { target: { value: "3fa85f64-5717-4562-b3fc-2c963f66afa6" } });
    fireEvent.click(screen.getByRole("button", { name: /log delay/i }));
    await waitFor(() => expect(taskExecutionApi.logDelay).toHaveBeenCalledWith("p1", "t1", { responsibility_type: "vendor", responsible_vendor_id: "3fa85f64-5717-4562-b3fc-2c963f66afa6", reason: "Cement delayed at source.", impact_days: 1 }));
    await waitFor(() => expect(screen.queryByLabelText("Reason")).not.toBeInTheDocument());
  });

  it("rejects a non-UUID vendor id before submitting", async () => {
    render(<TaskBlockerDelayPanel projectId="p1" task={task} onChanged={vi.fn()}/>);
    fireEvent.click(screen.getByRole("button", { name: /report delay/i }));
    fireEvent.change(screen.getByLabelText("Reason"), { target: { value: "Cement delayed at source." } });
    fireEvent.change(screen.getByLabelText(/vendor id/i), { target: { value: "vendor-123" } });
    expect(screen.getByRole("button", { name: /log delay/i })).toBeDisabled();
    expect(screen.getByText("Must be a valid UUID.")).toBeInTheDocument();
    expect(taskExecutionApi.logDelay).not.toHaveBeenCalled();
  });

  it("submits a non-vendor delay without a vendor id", async () => {
    taskExecutionApi.logDelay.mockResolvedValue({});
    render(<TaskBlockerDelayPanel projectId="p1" task={task} onChanged={vi.fn()}/>);
    fireEvent.click(screen.getByRole("button", { name: /report delay/i }));
    fireEvent.change(screen.getByLabelText("Responsibility"), { target: { value: "client" } });
    fireEvent.change(screen.getByLabelText("Reason"), { target: { value: "Client decision pending." } });
    fireEvent.change(screen.getByLabelText("Impact (days)"), { target: { value: "3" } });
    fireEvent.click(screen.getByRole("button", { name: /log delay/i }));
    await waitFor(() => expect(taskExecutionApi.logDelay).toHaveBeenCalledWith("p1", "t1", { responsibility_type: "client", responsible_vendor_id: null, reason: "Client decision pending.", impact_days: 3 }));
  });

  it("blocker and delay forms are independent - opening one closes the other", () => {
    render(<TaskBlockerDelayPanel projectId="p1" task={task} onChanged={vi.fn()}/>);
    fireEvent.click(screen.getByRole("button", { name: /report blocker/i }));
    expect(screen.getByLabelText("Type")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /report delay/i }));
    expect(screen.queryByLabelText("Type")).not.toBeInTheDocument();
    expect(screen.getByLabelText("Reason")).toBeInTheDocument();
  });
});
