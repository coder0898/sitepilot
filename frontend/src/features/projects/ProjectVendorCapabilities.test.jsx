import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { vendorAssignmentApi } from "../../api/vendorAssignmentApi";
import { ProjectVendorPanel } from "./components/ProjectVendorPanel";

vi.mock("../../api/vendorAssignmentApi", () => ({ vendorAssignmentApi: {
  listVendors: vi.fn(), listProjectVendors: vi.fn(), listCapabilityCategories: vi.fn(),
  mapVendor: vi.fn(), setVendorCapabilities: vi.fn(),
} }));

const project = { id: "p1", status: "active" };
const categories = [
  { id: "cat-electrical", name: "Electrical" },
  { id: "cat-partitions", name: "Partitions" },
];

function testVendor(overrides = {}) {
  return {
    id: "v1", name: "Test Vendor Co.", engagement_type: "main", parent_vendor_id: null,
    status: "active", contact_person: "Test Contact", phone: "9000000000", whatsapp: null,
    capability_categories: [], capability_category_ids: [],
    ...overrides,
  };
}

const mapping = {
  id: "m1", project_id: "p1", vendor_id: "v1", vendor_name: "Test Vendor Co.",
  engagement_type: "main", parent_vendor_id: null, mapped_by: "u1", created_at: "2026-08-05T00:00:00Z",
};

beforeEach(() => {
  vi.clearAllMocks();
  vendorAssignmentApi.listCapabilityCategories.mockResolvedValue(categories);
});

describe("ProjectVendorPanel - trade phase editing", () => {
  it("warns when a mapped vendor has no trade phase set", async () => {
    vendorAssignmentApi.listVendors.mockResolvedValue([testVendor()]);
    vendorAssignmentApi.listProjectVendors.mockResolvedValue([mapping]);
    render(<ProjectVendorPanel project={project} user={{ role: "project_manager", id: "u1" }}/>);

    expect(await screen.findByText(/no trade phase set/i)).toBeInTheDocument();
  });

  it("shows a mapped vendor's current trade phases as pills", async () => {
    vendorAssignmentApi.listVendors.mockResolvedValue([testVendor({
      capability_categories: ["Partitions"], capability_category_ids: ["cat-partitions"],
    })]);
    vendorAssignmentApi.listProjectVendors.mockResolvedValue([mapping]);
    render(<ProjectVendorPanel project={project} user={{ role: "project_manager", id: "u1" }}/>);

    expect(await screen.findByText("Partitions")).toBeInTheDocument();
    expect(screen.queryByText(/no trade phase set/i)).not.toBeInTheDocument();
  });

  it("lets a PM edit and save a vendor's trade phases", async () => {
    vendorAssignmentApi.listVendors.mockResolvedValue([testVendor()]);
    vendorAssignmentApi.listProjectVendors.mockResolvedValue([mapping]);
    vendorAssignmentApi.setVendorCapabilities.mockResolvedValue({
      ...testVendor({ capability_categories: ["Partitions"], capability_category_ids: ["cat-partitions"] }),
    });
    render(<ProjectVendorPanel project={project} user={{ role: "project_manager", id: "u1" }}/>);

    fireEvent.click(await screen.findByRole("button", { name: /edit/i }));
    fireEvent.click(screen.getByRole("checkbox", { name: /partitions/i }));
    fireEvent.click(screen.getByRole("button", { name: /save trade phases/i }));

    await waitFor(() => expect(vendorAssignmentApi.setVendorCapabilities).toHaveBeenCalledWith("v1", ["cat-partitions"]));
  });

  it("hides the Edit control for a role that cannot manage vendors", async () => {
    vendorAssignmentApi.listVendors.mockResolvedValue([testVendor()]);
    vendorAssignmentApi.listProjectVendors.mockResolvedValue([mapping]);
    render(<ProjectVendorPanel project={project} user={{ role: "supervisor", id: "u2" }}/>);

    await screen.findByText("Test Vendor Co.");
    expect(screen.queryByRole("button", { name: /edit/i })).not.toBeInTheDocument();
  });
});
