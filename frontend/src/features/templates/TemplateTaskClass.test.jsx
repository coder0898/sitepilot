import { fireEvent, render, screen, waitFor } from "@testing-library/react";
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
  it("offers Standard and Class A and saves the chosen value", async () => {
    const onSaved = renderEditor(task());
    const select = screen.getByLabelText("Task class");
    expect(select).toHaveValue("standard");
    expect([...select.options].map(option => option.value)).toEqual(["standard", "class_a"]);
    fireEvent.change(select, { target: { value: "class_a" } });
    fireEvent.click(screen.getByRole("button", { name: /Save task/ }));
    await waitFor(() => expect(onSaved).toHaveBeenCalledWith(expect.objectContaining({ task_class: "class_a", task_kind: null }), expect.anything()));
  });

  it("disables the class for approval gates and saves no class", async () => {
    const onSaved = renderEditor(task({ task_class: "class_a" }));
    fireEvent.change(screen.getByLabelText("Task kind"), { target: { value: "approval_gate" } });
    expect(screen.getByLabelText("Task class")).toBeDisabled();
    fireEvent.click(screen.getByRole("button", { name: /Save task/ }));
    await waitFor(() => expect(onSaved).toHaveBeenCalledWith(expect.objectContaining({ task_class: null, task_kind: "approval_gate" }), expect.anything()));
  });
});
