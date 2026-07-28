import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { templatesApi } from "../../api/templatesApi";
import { TemplatesPage } from "./TemplatesPage";
import { DashboardTab } from "../dashboard/DashboardTab";

vi.mock("../../api/templatesApi", () => ({ templatesApi: { list: vi.fn(), getVersion: vi.fn(), listTasks: vi.fn(), listGates: vi.fn() } }));

const published = {
  template_id: "template-1",
  template_code: "WORKVED-45",
  template_name: "Workved 45-Day Interior Delivery",
  template_description: "Approved schedule",
  version_id: "version-published",
  version_no: 1,
  status: "published",
  is_current_published: true,
  duration_days: 45,
  task_count: 99,
  dependency_count: 38,
  gate_count: 32,
  created_at: "2026-07-24T10:00:00Z",
  published_at: "2026-07-25T10:00:00Z",
};
const draft = { ...published, version_id: "version-draft", version_no: 2, status: "draft", is_current_published: false, published_at: null };
const response = (items = [published], overrides = {}) => ({
  items,
  pagination: { page: 1, page_size: 20, total: items.length, total_pages: items.length ? 1 : 0, ...overrides },
});
const renderPage = (role = "admin") => render(<TemplatesPage user={{ role }} debounceMs={0} />);

beforeEach(() => {
  vi.clearAllMocks();
  templatesApi.getVersion.mockResolvedValue(published);
  templatesApi.listTasks.mockResolvedValue({
    items: [],
    pagination: { page: 1, page_size: 20, total: 0, total_pages: 0 },
  });
});

describe("TemplatesPage", () => {
  it("renders published data, persisted counts, mobile cards, and selected version state", async () => {
    templatesApi.list.mockResolvedValue(response());
    const { container } = renderPage();
    const card = await screen.findByTestId("template-card-version-published");
    expect(within(card).getByText("99")).toBeInTheDocument();
    expect(within(card).getByText("38")).toBeInTheDocument();
    expect(within(card).getByText("32")).toBeInTheDocument();
    expect(within(card).getByText("Current published")).toBeInTheDocument();
    fireEvent.click(within(card).getByRole("button", { name: /view details/i }));
    const feature = container.querySelector("[data-template-view]");
    expect(feature).toHaveAttribute("data-template-view", "detail");
    expect(feature).toHaveAttribute("data-selected-version-id", "version-published");
  });

  it("shows drafts and a working status filter only to Super Admin", async () => {
    templatesApi.list.mockResolvedValue(response([published, draft], { total: 2 }));
    renderPage("super_admin");
    expect(await screen.findByTestId("template-card-version-draft")).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("Filter template status"), { target: { value: "draft" } });
    await waitFor(() => expect(templatesApi.list.mock.calls.at(-1)[0]).toMatchObject({ status: "draft", page: 1 }));
  });

  it.each(["admin", "project_manager"])("does not expose the draft filter to %s", async role => {
    templatesApi.list.mockResolvedValue(response());
    renderPage(role);
    await screen.findByTestId("template-card-version-published");
    expect(screen.queryByLabelText("Filter template status")).not.toBeInTheDocument();
    expect(templatesApi.list.mock.calls.every(([params]) => !("status" in params))).toBe(true);
  });

  it("distinguishes loading, empty database, and filtered no-match states", async () => {
    let resolveRequest;
    templatesApi.list.mockReturnValue(new Promise(resolve => { resolveRequest = resolve; }));
    const first = renderPage();
    expect(screen.getByText("Loading approved templates...")).toBeInTheDocument();
    resolveRequest(response([]));
    expect(await screen.findByText("No template versions available")).toBeInTheDocument();
    first.unmount();

    templatesApi.list.mockResolvedValue(response([]));
    renderPage();
    fireEvent.change(screen.getByLabelText("Search templates"), { target: { value: "missing" } });
    expect(await screen.findByText("No templates match these filters")).toBeInTheDocument();
  });

  it("shows API/session errors and retries", async () => {
    templatesApi.list.mockRejectedValueOnce(new Error("Session expired. Please login again.")).mockResolvedValueOnce(response());
    renderPage();
    expect(await screen.findByRole("alert")).toHaveTextContent("Session expired");
    fireEvent.click(screen.getByRole("button", { name: /retry/i }));
    expect(await screen.findByTestId("template-card-version-published")).toBeInTheDocument();
    expect(templatesApi.list).toHaveBeenCalledTimes(2);
  });

  it("sends backend search and pagination requests and resets the page for search", async () => {
    templatesApi.list.mockResolvedValue(response([published], { total: 25, total_pages: 2 }));
    renderPage();
    await screen.findByTestId("template-card-version-published");
    fireEvent.click(screen.getByRole("button", { name: /next/i }));
    await waitFor(() => expect(templatesApi.list.mock.calls.at(-1)[0]).toMatchObject({ page: 2 }));
    fireEvent.change(screen.getByLabelText("Search templates"), { target: { value: " workved " } });
    await waitFor(() => expect(templatesApi.list.mock.calls.at(-1)[0]).toMatchObject({ search: "workved", page: 1 }));
  });
  it("clears selected draft state immediately when the authenticated identity or role changes", async () => {
    templatesApi.list.mockResolvedValue(response([draft]));
    templatesApi.getVersion.mockResolvedValue({ ...draft, template_name: "Secret draft schedule", task_count: 0, dependency_count: 0, gate_count: 0, duration_days: 45 });
    const view = render(<DashboardTab tab="templates" loading={false} data={{}} user={{ id: "user-1", role: "super_admin" }} action={vi.fn()} />);
    const card = await screen.findByTestId("template-card-version-draft");
    fireEvent.click(within(card).getByRole("button", { name: /view details/i }));
    expect(await screen.findByText("Secret draft schedule")).toBeInTheDocument();

    templatesApi.list.mockResolvedValue(response([published]));
    view.rerender(<DashboardTab tab="templates" loading={false} data={{}} user={{ id: "user-1", role: "admin" }} action={vi.fn()} />);
    expect(await screen.findByText("Template library")).toBeInTheDocument();
    expect(screen.queryByText("Secret draft schedule")).not.toBeInTheDocument();
    expect(screen.queryByLabelText("Filter template status")).not.toBeInTheDocument();
  });
});
