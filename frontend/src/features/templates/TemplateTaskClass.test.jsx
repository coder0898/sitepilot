import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { TemplateTaskEditorModal } from "./components/TemplateTaskEditorModal";

const task = (overrides = {}) => ({
  id: "task-1", code: "T010", sequence_no: 10, title: "Pressure test", description: "", schedule_classification: "execution",
  planned_start_day: 5, planned_end_day: 6, phase: "", category: "", applicability: "mandatory",
  task_class: null, task_kind: null, evidence_required: false, duration_days: 2, ...overrides,
});

function renderEditor(existing) {
  const onSaved = vi.fn().mockResolvedValue(undefined);
  render(<TemplateTaskEditorModal task={existing} tasks={[]} durationDays={45} revisionToken="rev-1" onClose={vi.fn()} onSaved={onSaved}/>);
  return onSaved;
}

describe("Template task class", () => {
  it("offers Standard and Class A, explains each workflow and saves the choice", async () => {
    const onSaved = renderEditor(task());
    const group = screen.getByRole("radiogroup", { name: "Task class" });
    const standard = within(group).getByRole("radio", { name: /standard/i });
    const classA = within(group).getByRole("radio", { name: /class a/i });
    expect(standard).toBeChecked();
    expect(within(group).getByText(/a PM or Admin checks it. Then it is complete/)).toBeInTheDocument();
    expect(within(group).getByText(/then a different PM or Admin approves/)).toBeInTheDocument();
    fireEvent.click(classA);
    fireEvent.click(screen.getByRole("button", { name: /Save task/ }));
    await waitFor(() => expect(onSaved).toHaveBeenCalledWith(expect.objectContaining({ task_class: "class_a", task_kind: null }), expect.anything(), expect.anything()));
  });

  it("keeps a task's class exactly as stored when other fields change", async () => {
    const onSaved = renderEditor(task({ task_class: null }));
    fireEvent.change(screen.getByLabelText("Task name"), { target: { value: "Pressure test 2" } });
    fireEvent.click(screen.getByRole("button", { name: /Save task/ }));
    await waitFor(() => expect(onSaved).toHaveBeenCalledWith(expect.objectContaining({ task_class: null }), expect.anything(), expect.anything()));
  });

  it("hides the task type for ordinary tasks", () => {
    renderEditor(task());
    expect(screen.queryByLabelText("Task type")).not.toBeInTheDocument();
  });

  it("keeps a legacy approval task editable and saves no class for it", async () => {
    const onSaved = renderEditor(task({ task_kind: "approval_gate", task_class: null }));
    expect(screen.getByLabelText("Task type")).toHaveValue("approval_gate");
    expect(screen.queryByRole("radiogroup", { name: "Task class" })).not.toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("Task name"), { target: { value: "Get approval" } });
    fireEvent.click(screen.getByRole("button", { name: /Save task/ }));
    await waitFor(() => expect(onSaved).toHaveBeenCalledWith(expect.objectContaining({ task_class: null, task_kind: "approval_gate" }), expect.anything(), expect.anything()));
  });

  it("can turn a legacy approval task back into ordinary work", async () => {
    const onSaved = renderEditor(task({ task_kind: "approval_gate" }));
    fireEvent.change(screen.getByLabelText("Task type"), { target: { value: "" } });
    fireEvent.click(screen.getByRole("radio", { name: /class a/i }));
    fireEvent.click(screen.getByRole("button", { name: /Save task/ }));
    await waitFor(() => expect(onSaved).toHaveBeenCalledWith(expect.objectContaining({ task_class: "class_a", task_kind: null }), expect.anything(), expect.anything()));
  });
});

describe("Template task schedule", () => {
  it("does not offer Pre-Activation for an ordinary task", () => {
    renderEditor(task());
    expect(screen.queryByLabelText("Schedule")).not.toBeInTheDocument();
    expect([...screen.getByLabelText("Phase").options].map(option => option.value)).not.toContain("Pre-Activation");
  });

  it("keeps a legacy Pre-Activation task readable and lets the Admin move it onto project days", async () => {
    const onSaved = renderEditor(task({ schedule_classification: "pre_activation", planned_start_day: null, planned_end_day: null, phase: "Pre-Activation" }));
    expect(screen.getByLabelText("Phase")).toHaveValue("Pre-Activation");
    expect(screen.getByText(/happens before the project starts/i)).toBeInTheDocument();
    expect(screen.getByLabelText("Starts on day")).toBeDisabled();
    fireEvent.click(screen.getByRole("button", { name: /schedule it on project days/i }));
    fireEvent.change(screen.getByLabelText("Starts on day"), { target: { value: "3" } });
    fireEvent.change(screen.getByLabelText("Ends on day"), { target: { value: "4" } });
    fireEvent.click(screen.getByRole("button", { name: /Save task/ }));
    await waitFor(() => expect(onSaved).toHaveBeenCalledWith(expect.objectContaining({
      schedule_classification: "execution", planned_start_day: 3, planned_end_day: 4, duration_days: 2,
    }), expect.anything(), expect.anything()));
  });

  it("asks in plain words whether the task is required on every project", async () => {
    const onSaved = renderEditor(task());
    const group = screen.getByRole("radiogroup", { name: "Required on every project?" });
    fireEvent.click(within(group).getByRole("radio", { name: /no/i }));
    fireEvent.click(screen.getByRole("button", { name: /Save task/ }));
    await waitFor(() => expect(onSaved).toHaveBeenCalledWith(expect.objectContaining({ applicability: "conditional" }), expect.anything(), expect.anything()));
  });
});
