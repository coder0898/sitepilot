import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { projectsApi } from "../../api/projectsApi";
import { ProjectLifecyclePane } from "./components/ProjectLifecyclePane";

vi.mock("../../api/projectsApi", () => ({
  projectsApi: { setStatus: vi.fn(), restore: vi.fn(), remove: vi.fn() },
}));

function project(overrides = {}) {
  return {
    id: "p1", code: "PRJ-1", name: "test123", client_name: "Test2",
    status: "archived", template_version_id: "v1", memberships: [{ id: "m1", project_role: "project_manager" }],
    setup: { activation_ready: true },
    ...overrides,
  };
}

function renderPane(user, overrides = {}) {
  return render(<ProjectLifecyclePane
    project={project(overrides)}
    user={user}
    onChanged={vi.fn().mockResolvedValue(undefined)}
    onDeleted={vi.fn()}
  />);
}

beforeEach(() => {
  vi.clearAllMocks();
  projectsApi.restore.mockResolvedValue({ id: "p1", status: "draft" });
});

describe("Archived project lifecycle", () => {
  it("offers an Admin a way back out of the archive", async () => {
    renderPane({ role: "admin", id: "u-admin" });
    const button = screen.getByRole("button", { name: /restore project/i });
    expect(button).toBeDisabled();

    fireEvent.change(screen.getByLabelText("Reason for restoring"), { target: { value: "Archived in error." } });
    fireEvent.click(button);

    await waitFor(() => expect(projectsApi.restore).toHaveBeenCalledWith("p1", "Archived in error."));
  });

  it("warns that an active project comes back on hold rather than running", () => {
    renderPane({ role: "admin", id: "u-admin" });
    expect(screen.getByText(/comes back/i)).toHaveTextContent(/on hold/i);
  });

  it("never tells an Admin that this is an Admin-only action", () => {
    // Regression: archived is terminal in change_status, so the pane had no
    // transitions and fell through to a role message that was simply wrong.
    renderPane({ role: "admin", id: "u-admin" });
    expect(screen.queryByText(/Admin-only actions/i)).not.toBeInTheDocument();
  });

  it("explains the real blocker to a role that cannot restore", () => {
    renderPane({ role: "project_manager", id: "u-pm" });
    expect(screen.getByText(/archived\. Only an Admin can restore it/i)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /restore project/i })).not.toBeInTheDocument();
  });

  it("surfaces a failed restore without clearing the reason", async () => {
    projectsApi.restore.mockRejectedValue(new Error("Only Admin can restore an archived project."));
    renderPane({ role: "admin", id: "u-admin" });
    fireEvent.change(screen.getByLabelText("Reason for restoring"), { target: { value: "Archived in error." } });
    fireEvent.click(screen.getByRole("button", { name: /restore project/i }));

    expect(await screen.findByRole("alert")).toHaveTextContent("Only Admin can restore an archived project.");
    expect(screen.getByLabelText("Reason for restoring")).toHaveValue("Archived in error.");
  });

  it("still offers ordinary transitions on a non-archived project", () => {
    renderPane({ role: "admin", id: "u-admin" }, { status: "active" });
    expect(screen.getByLabelText("Move project to")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /restore project/i })).not.toBeInTheDocument();
  });
});
