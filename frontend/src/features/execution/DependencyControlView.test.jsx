import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { taskExecutionApi } from "../../api/taskExecutionApi";
import { DependencyControlView } from "./components/DependencyControlView";

vi.mock("../../api/taskExecutionApi", () => ({ taskExecutionApi: {
  list: vi.fn(), detail: vi.fn(), listExternalApprovals: vi.fn(),
} }));

const admin = { id: "u-adm", role: "admin" };
const project = { id: "p1", memberships: [] };

const dep = (overrides = {}) => ({
  id: "d1", sequence: 1, dependency_type: "finish_to_start", blocking: true, rule_text: null,
  predecessor_project_task_id: "pt-1", predecessor_code: "T001", predecessor_title: "Freeze layout", predecessor_included: true,
  successor_project_task_id: "pt-2", successor_code: "T002", successor_title: "Start framing", successor_included: true,
  excluded_task_warning: false, source: "template",
  ...overrides,
});

const execTask = (overrides = {}) => ({
  id: "e1", original_code: "T001", title: "Freeze layout", lifecycle_status: "planned",
  phase: "Design", category: "Planning", planned_start_date: "2026-08-01", planned_end_date: "2026-08-02",
  readiness: { state: "ready", reasons: [], advisories: [] }, variance: null,
  ...overrides,
});

beforeEach(() => {
  vi.clearAllMocks();
  taskExecutionApi.listExternalApprovals.mockResolvedValue([]);
});

describe("DependencyControlView", () => {
  it("computes Finish-to-Start status as Blocking while the predecessor is only planned", async () => {
    taskExecutionApi.list.mockResolvedValue([execTask({ lifecycle_status: "planned" }), execTask({ id: "e2", original_code: "T002", title: "Start framing" })]);
    const dependencies = { items: [dep()], total: 1, excluded_warning_count: 0 };
    render(<DependencyControlView projectId="p1" project={project} user={admin} dependencies={dependencies}/>);
    const row = await screen.findByText("Freeze layout");
    expect(within(row.closest("tr")).getByText("Blocking")).toBeInTheDocument();
  });

  it("computes Finish-to-Start status as Satisfied once the predecessor is completed", async () => {
    taskExecutionApi.list.mockResolvedValue([execTask({ lifecycle_status: "completed" }), execTask({ id: "e2", original_code: "T002", title: "Start framing" })]);
    const dependencies = { items: [dep()], total: 1, excluded_warning_count: 0 };
    render(<DependencyControlView projectId="p1" project={project} user={admin} dependencies={dependencies}/>);
    const row = await screen.findByText("Freeze layout");
    expect(within(row.closest("tr")).getByText("Satisfied")).toBeInTheDocument();
  });

  it("computes Start-to-Start status: satisfied once predecessor is in_progress", async () => {
    taskExecutionApi.list.mockResolvedValue([
      execTask({ lifecycle_status: "in_progress" }),
      execTask({ id: "e2", original_code: "T002", title: "Start framing" }),
    ]);
    const dependencies = { items: [dep({ dependency_type: "start_to_start" })], total: 1, excluded_warning_count: 0 };
    render(<DependencyControlView projectId="p1" project={project} user={admin} dependencies={dependencies}/>);
    const row = await screen.findByText("Freeze layout");
    expect(within(row.closest("tr")).getByText("Satisfied")).toBeInTheDocument();
  });

  it("shows Unknown status without guessing when the predecessor isn't resolvable in the execution list", async () => {
    taskExecutionApi.list.mockResolvedValue([execTask({ id: "e2", original_code: "T002", title: "Start framing" })]); // no T001
    const dependencies = { items: [dep()], total: 1, excluded_warning_count: 0 };
    render(<DependencyControlView projectId="p1" project={project} user={admin} dependencies={dependencies}/>);
    const row = await screen.findByText("Freeze layout");
    // Both the "Predecessor Status" and "Dependency Status" columns show
    // "Unknown" here (the predecessor itself is unresolvable), so this
    // asserts at least one rather than picking a single ambiguous match.
    expect(within(row.closest("tr")).getAllByText("Unknown").length).toBeGreaterThan(0);
  });

  it("shows real KPI counts derived from the dependency list", async () => {
    taskExecutionApi.list.mockResolvedValue([
      execTask({ lifecycle_status: "completed" }),
      execTask({ id: "e2", original_code: "T002", title: "Start framing" }),
      execTask({ id: "e3", original_code: "T003", title: "Pour slab", lifecycle_status: "in_progress" }),
    ]);
    const dependencies = {
      items: [
        dep({ id: "d1" }), // finish_to_start, T001->T002, satisfied (completed)
        dep({ id: "d2", dependency_type: "start_to_start", predecessor_code: "T003", predecessor_title: "Pour slab", successor_code: "T002", successor_title: "Start framing" }), // satisfied (in_progress)
      ],
      total: 2, excluded_warning_count: 0,
    };
    render(<DependencyControlView projectId="p1" project={project} user={admin} dependencies={dependencies}/>);
    const group = await screen.findByRole("group", { name: /dependency summary/i });
    // Total (2) and Satisfied (2) both land on "2"; Finish-to-Start and
    // Start-to-Start both land on "1" - assert counts, not single matches.
    expect(within(group).getAllByText("2").length).toBe(2);
    expect(within(group).getAllByText("1").length).toBe(2);
    expect(within(group).getByText("0")).toBeInTheDocument(); // Blocking
  });

  it("filters by search", async () => {
    taskExecutionApi.list.mockResolvedValue([execTask(), execTask({ id: "e2", original_code: "T002", title: "Start framing" })]);
    const dependencies = {
      items: [
        dep({ id: "d1" }),
        dep({ id: "d2", predecessor_code: "T009", predecessor_title: "Unrelated task", successor_code: "T002", successor_title: "Start framing" }),
      ],
      total: 2, excluded_warning_count: 0,
    };
    render(<DependencyControlView projectId="p1" project={project} user={admin} dependencies={dependencies}/>);
    await screen.findByText("Freeze layout");
    fireEvent.change(screen.getByPlaceholderText(/search by task code or title/i), { target: { value: "Unrelated" } });
    await waitFor(() => expect(screen.queryByText("Freeze layout")).not.toBeInTheDocument());
    expect(screen.getByText("Unrelated task")).toBeInTheDocument();
  });

  it("filters by dependency type and by status via the quick chips", async () => {
    taskExecutionApi.list.mockResolvedValue([
      execTask({ lifecycle_status: "planned" }), // T001, blocking for FS
      execTask({ id: "e2", original_code: "T002", title: "Start framing" }),
      execTask({ id: "e3", original_code: "T003", title: "Pour slab", lifecycle_status: "in_progress" }), // satisfied for SS
    ]);
    const dependencies = {
      items: [
        dep({ id: "d1" }), // FS, blocking
        dep({ id: "d2", dependency_type: "start_to_start", predecessor_code: "T003", predecessor_title: "Pour slab", successor_code: "T002", successor_title: "Start framing" }), // SS, satisfied
      ],
      total: 2, excluded_warning_count: 0,
    };
    render(<DependencyControlView projectId="p1" project={project} user={admin} dependencies={dependencies}/>);
    await screen.findByText("Freeze layout");
    fireEvent.click(screen.getByRole("button", { name: /^blocking \(1\)$/i }));
    await waitFor(() => expect(screen.queryByText("Pour slab")).not.toBeInTheDocument());
    expect(screen.getByText("Freeze layout")).toBeInTheDocument();
  });

  it("opens the dependency detail drawer on row click and shows the blocking explanation", async () => {
    taskExecutionApi.list.mockResolvedValue([execTask({ lifecycle_status: "planned" }), execTask({ id: "e2", original_code: "T002", title: "Start framing" })]);
    const dependencies = { items: [dep()], total: 1, excluded_warning_count: 0 };
    render(<DependencyControlView projectId="p1" project={project} user={admin} dependencies={dependencies}/>);
    await screen.findByText("Freeze layout");
    expect(screen.queryByText("Dependency Detail")).not.toBeInTheDocument();
    fireEvent.click(screen.getByText("Freeze layout"));
    expect(await screen.findByText("Dependency Detail")).toBeInTheDocument();
    expect(screen.getByText("The successor task cannot start until the predecessor task is completed.")).toBeInTheDocument();
  });

  it("opens the task drawer from a Quick Action and disables the button when a task isn't resolvable", async () => {
    taskExecutionApi.list.mockResolvedValue([execTask({ lifecycle_status: "planned" })]); // no T002 (successor)
    taskExecutionApi.detail.mockResolvedValue({
      ...execTask({ lifecycle_status: "planned" }), description: "Freeze the layout.",
      predecessors: [], progress_updates: [], verifications: [], approvals: [],
      blockers: [], delays: [], support_assignments: [], audit_events: [],
    });
    const dependencies = { items: [dep()], total: 1, excluded_warning_count: 0 };
    render(<DependencyControlView projectId="p1" project={project} user={admin} dependencies={dependencies}/>);
    fireEvent.click(await screen.findByText("Freeze layout"));
    await screen.findByText("Dependency Detail");
    expect(screen.getByRole("button", { name: /view successor task/i })).toBeDisabled();
    fireEvent.click(screen.getByRole("button", { name: /view predecessor task/i }));
    expect(await screen.findByText("Freeze the layout.")).toBeInTheDocument();
  });

  it("shows an empty state when the project has no dependencies", async () => {
    taskExecutionApi.list.mockResolvedValue([]);
    render(<DependencyControlView projectId="p1" project={project} user={admin} dependencies={{ items: [], total: 0, excluded_warning_count: 0 }}/>);
    expect(await screen.findByText("No dependencies were generated for this project")).toBeInTheDocument();
  });

  it("shows 6 dependency rows by default, then Load More/Show Less paginate the rest", async () => {
    taskExecutionApi.list.mockResolvedValue([]);
    const items = Array.from({ length: 8 }, (_, i) => dep({
      id: `d${i}`,
      predecessor_code: `P${i}`, predecessor_title: `Predecessor ${i}`,
      successor_code: `S${i}`, successor_title: `Successor ${i}`,
    }));
    render(<DependencyControlView projectId="p1" project={project} user={admin} dependencies={{ items, total: 8, excluded_warning_count: 0 }}/>);

    const bodyRows = () => screen.getAllByRole("row").filter(row => within(row).queryAllByRole("cell").length > 0);
    await waitFor(() => expect(bodyRows()).toHaveLength(6));
    expect(screen.queryByText("Show Less")).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Load More" }));
    await waitFor(() => expect(bodyRows()).toHaveLength(8));
    expect(screen.queryByRole("button", { name: "Load More" })).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Show Less" }));
    await waitFor(() => expect(bodyRows()).toHaveLength(6));
  });
});
