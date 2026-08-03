import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { taskExecutionApi } from "../../api/taskExecutionApi";
import { TaskProgressForm } from "./components/TaskProgressForm";

vi.mock("../../api/taskExecutionApi", () => ({ taskExecutionApi: { submitProgress: vi.fn() } }));

const task = { id: "t1" };

beforeEach(() => {
  vi.clearAllMocks();
});

describe("TaskProgressForm", () => {
  it("disables submit until a note, status claim, or file is provided", async () => {
    render(<TaskProgressForm projectId="p1" task={task} onSubmitted={vi.fn()}/>);
    expect(screen.getByRole("button", { name: /submit progress/i })).toBeDisabled();
    fireEvent.change(screen.getByLabelText("Note"), { target: { value: "Crew mobilised." } });
    expect(screen.getByRole("button", { name: /submit progress/i })).toBeEnabled();
  });

  it("submits a note-only update as multipart form data and clears the form", async () => {
    taskExecutionApi.submitProgress.mockResolvedValue({});
    const onSubmitted = vi.fn();
    render(<TaskProgressForm projectId="p1" task={task} onSubmitted={onSubmitted}/>);
    fireEvent.change(screen.getByLabelText("Note"), { target: { value: "Crew mobilised." } });
    fireEvent.change(screen.getByLabelText(/status claim/i), { target: { value: "Ready for review" } });
    fireEvent.click(screen.getByRole("button", { name: /submit progress/i }));

    await waitFor(() => expect(taskExecutionApi.submitProgress).toHaveBeenCalledTimes(1));
    const [projectId, taskId, formData] = taskExecutionApi.submitProgress.mock.calls[0];
    expect(projectId).toBe("p1");
    expect(taskId).toBe("t1");
    expect(formData).toBeInstanceOf(FormData);
    expect(formData.get("note")).toBe("Crew mobilised.");
    expect(formData.get("status_claim")).toBe("Ready for review");
    expect(formData.has("evidence")).toBe(false);
    await waitFor(() => expect(onSubmitted).toHaveBeenCalledTimes(1));
    expect(screen.getByLabelText("Note")).toHaveValue("");
  });

  it("includes the evidence file when one is selected", async () => {
    taskExecutionApi.submitProgress.mockResolvedValue({});
    render(<TaskProgressForm projectId="p1" task={task} onSubmitted={vi.fn()}/>);
    const file = new File(["binary"], "site.jpg", { type: "image/jpeg" });
    fireEvent.change(screen.getByLabelText(/evidence photo or pdf/i), { target: { files: [file] } });
    fireEvent.click(screen.getByRole("button", { name: /submit progress/i }));
    await waitFor(() => expect(taskExecutionApi.submitProgress).toHaveBeenCalledTimes(1));
    const formData = taskExecutionApi.submitProgress.mock.calls[0][2];
    expect(formData.get("evidence").name).toBe("site.jpg");
  });

  it("shows a backend error inline without clearing the form", async () => {
    taskExecutionApi.submitProgress.mockRejectedValue(new Error("Disallowed MIME type."));
    render(<TaskProgressForm projectId="p1" task={task} onSubmitted={vi.fn()}/>);
    fireEvent.change(screen.getByLabelText("Note"), { target: { value: "Crew mobilised." } });
    fireEvent.click(screen.getByRole("button", { name: /submit progress/i }));
    expect(await screen.findByText("Disallowed MIME type.")).toBeInTheDocument();
    expect(screen.getByLabelText("Note")).toHaveValue("Crew mobilised.");
  });
});
