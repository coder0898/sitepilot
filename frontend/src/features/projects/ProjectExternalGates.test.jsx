import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { projectsApi } from "../../api/projectsApi";
import { ProjectExternalGates } from "./components/ProjectExternalGates";

vi.mock("../../api/projectsApi", () => ({ projectsApi: {
  externalGates: vi.fn(), generateGates: vi.fn(), decideGateApplicability: vi.fn(), gateApplicabilityHistory: vi.fn(), createManualGate: vi.fn(), templateReviewTasks: vi.fn(),
} }));
const project = { id: "project-1", status: "draft" };
const generated = { project_id: "project-1", total: 2, items: [
  { id: "g1", code: "E001", sequence: 1, approval_name: "Society approval", description: "Approval", mapping_classification: "exact", broad_mapping_text: null, requires_configuration: false, status: "pending_review", applicability_state: "pending_review", source: "template", accountable_pm_name: "PM Owner", exact_task_count: 2 },
  { id: "g2", code: "E002", sequence: 2, approval_name: "Client inputs", description: null, mapping_classification: "broad_text", broad_mapping_text: "Relevant finish tasks", requires_configuration: true, status: "pending_review", applicability_state: "not_applicable", source: "template", accountable_pm_name: "PM Owner", exact_task_count: 0 },
] };

beforeEach(() => {
  vi.clearAllMocks();
  projectsApi.externalGates.mockResolvedValue(generated);
  projectsApi.decideGateApplicability.mockResolvedValue({ applicability_state: "applicable" });
  projectsApi.gateApplicabilityHistory.mockResolvedValue([]);
  projectsApi.templateReviewTasks.mockResolvedValue({ items: [{ id: "t1", code: "T001", title: "Mobilize", phase: "Mobilization", category: "Site", included: true }] });
  projectsApi.createManualGate.mockResolvedValue({ gate_id: "manual-gate-1", source_type: "project_manual" });
});

describe("Project external gate applicability", () => {
  it("shows status, source, PM owner and applicability controls separately from tasks", async () => {
    render(<ProjectExternalGates project={project} user={{ role: "admin" }}/>);
    expect(await screen.findByText("2 gates")).toBeInTheDocument();
    expect(screen.getAllByText("Template")).toHaveLength(2);
    expect(screen.getAllByText("PM Owner")).toHaveLength(2);
    expect(screen.getByText("not applicable")).toBeInTheDocument();
    expect(screen.getAllByRole("button", { name: /^Applicable$/i })).toHaveLength(2);
  });

  it("requires a reason for Not Applicable and refreshes after success", async () => {
    projectsApi.externalGates.mockResolvedValueOnce(generated).mockResolvedValueOnce(generated);
    render(<ProjectExternalGates project={project} user={{ role: "admin" }}/>);
    await screen.findByText("2 gates");
    fireEvent.click(screen.getAllByRole("button", { name: /^Not Applicable$/i })[0]);
    fireEvent.click(screen.getByRole("button", { name: /confirm not applicable/i }));
    expect(screen.getByRole("alert")).toHaveTextContent(/reason is required/i);
    fireEvent.change(screen.getByLabelText(/reason/i), { target: { value: "Not required at this site" } });
    fireEvent.click(screen.getByRole("button", { name: /confirm not applicable/i }));
    await waitFor(() => expect(projectsApi.decideGateApplicability).toHaveBeenCalledWith("project-1", "g1", { decision: "not_applicable", reason: "Not required at this site" }));
    await waitFor(() => expect(projectsApi.externalGates).toHaveBeenCalledTimes(2));
  });

  it("gives the assigned PM a read-only view: applicability belongs to Admin", async () => {
    render(<ProjectExternalGates project={project} user={{ role: "project_manager" }}/>);
    await screen.findByText("2 gates");
    expect(screen.queryByRole("button", { name: /add manual approval/i })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /applicable/i })).not.toBeInTheDocument();
    // History stays, so the PM can see which approvals were ruled out and why.
    expect(screen.getAllByRole("button", { name: /history/i }).length).toBeGreaterThan(0);
  });

  it("renders append-only decision history", async () => {
    projectsApi.gateApplicabilityHistory.mockResolvedValue([{ id: "d1", decision: "not_applicable", reason: "Not required", actor_name: "Admin", decided_at: "2026-07-29T10:00:00Z" }]);
    render(<ProjectExternalGates project={project} user={{ role: "project_manager" }}/>);
    await screen.findByText("2 gates");
    fireEvent.click(screen.getAllByRole("button", { name: /history/i })[0]);
    expect(await screen.findByText("Not required")).toBeInTheDocument();
    expect(screen.getByText("By Admin")).toBeInTheDocument();
  });

  it("creates a blocking manual approval from included project tasks", async () => {
    projectsApi.externalGates.mockResolvedValueOnce(generated).mockResolvedValueOnce(generated);
    render(<ProjectExternalGates project={project} user={{ role: "admin" }}/>);
    await screen.findByText("2 gates");
    fireEvent.click(screen.getByRole("button", { name: /add manual approval/i }));
    expect(await screen.findByText(/project-only approval/i)).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText(/^title$/i), { target: { value: "Landlord approval" } });
    fireEvent.change(screen.getByLabelText(/external party/i), { target: { value: "Landlord" } });
    fireEvent.change(screen.getByLabelText(/project day/i), { target: { value: "5" } });
    fireEvent.click(await screen.findByRole("checkbox", { name: /T001/i }));
    fireEvent.change(screen.getByLabelText(/^impact$/i), { target: { value: "Blocks fit-out" } });
    fireEvent.change(screen.getByLabelText(/^reason$/i), { target: { value: "Project-specific requirement" } });
    fireEvent.click(screen.getByRole("button", { name: /add manual approval/i }));
    await waitFor(() => expect(projectsApi.createManualGate).toHaveBeenCalledWith("project-1", expect.objectContaining({ blocking: true, affected_project_task_ids: ["t1"] })));
  });

  it("requires an affected task for a blocking manual approval and uses mobile actions", async () => {
    render(<ProjectExternalGates project={project} user={{ role: "admin" }}/>);
    await screen.findByText("2 gates");
    fireEvent.click(screen.getByRole("button", { name: /add manual approval/i }));
    await screen.findByText(/project-only approval/i);
    fireEvent.change(screen.getByLabelText(/^title$/i), { target: { value: "Approval" } });
    fireEvent.change(screen.getByLabelText(/external party/i), { target: { value: "Client" } });
    fireEvent.change(screen.getByLabelText(/project day/i), { target: { value: "2" } });
    fireEvent.change(screen.getByLabelText(/^impact$/i), { target: { value: "Blocks work" } });
    fireEvent.change(screen.getByLabelText(/^reason$/i), { target: { value: "Needed" } });
    fireEvent.click(screen.getByRole("button", { name: /add manual approval/i }));
    expect(screen.getByRole("alert")).toHaveTextContent(/select at least one included task/i);
  });

  it("uses mobile two-column controls", async () => {
    render(<ProjectExternalGates project={project} user={{ role: "admin" }}/>);
    await screen.findByText("2 gates");
    const applicable = screen.getAllByRole("button", { name: /^Applicable$/i })[0];
    expect(applicable.parentElement).toHaveClass("grid-cols-2");
  });
});
