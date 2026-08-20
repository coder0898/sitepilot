import { fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { AppLayout } from "./AppLayout";

const SEVEN_TABS = [
  ["projects", "Projects"],
  ["admin_overview", "Portfolio"],
  ["templates", "Templates"],
  ["execution", "Execution"],
  ["communication", "Vendor Hub"],
  ["broadcasts", "Communication"],
  ["users", "Users & Access"],
];

// Deliberately avoids "Vendor Hub"/"Role Permissions" - MobileNavigation
// rewrites those two specific labels for display, which is unrelated to
// the overflow behaviour under test here.
const THREE_TABS = [
  ["execution", "Execution"],
  ["broadcasts", "Communication"],
  ["users", "Users & Access"],
];

const USER = { role: "admin", name: "Admin User", email: "admin@example.com" };

function renderLayout(tabs, activeTab = tabs[0][0]) {
  return render(
    <AppLayout user={USER} tabs={tabs} activeTab={activeTab} onTabChange={vi.fn()} onLogout={vi.fn()} onRefresh={vi.fn()}>
      <p>Page content</p>
    </AppLayout>,
  );
}

describe("MobileNavigation overflow", () => {
  it("renders every tab directly with no More button when there are 5 or fewer", () => {
    renderLayout(THREE_TABS);
    const nav = screen.getByRole("navigation", { name: "Mobile navigation" });
    expect(within(nav).queryByRole("button", { name: /more/i })).toBeNull();
    for (const [, label] of THREE_TABS) {
      expect(within(nav).getByText(label)).toBeInTheDocument();
    }
  });

  it("caps the bottom bar at 5 slots and moves the rest behind a More button, instead of squeezing every label", () => {
    renderLayout(SEVEN_TABS);
    const nav = screen.getByRole("navigation", { name: "Mobile navigation" });

    // 4 primary tabs + 1 "More" slot = 5, never 7 squeezed into one row.
    expect(within(nav).getAllByRole("button")).toHaveLength(5);
    expect(within(nav).getByRole("button", { name: /more/i })).toBeInTheDocument();

    // The last 3 tabs (per MAX_VISIBLE_MOBILE_TABS - 1 = 4 primary slots)
    // are not rendered as their own squeezed buttons in the bar itself.
    expect(within(nav).queryByText("Vendor Hub")).toBeNull();
    expect(within(nav).queryByText("Communication")).toBeNull();
    expect(within(nav).queryByText("Users & Access")).toBeNull();
  });

  it("opens a sheet with full, untruncated labels for the overflow tabs on tapping More", () => {
    renderLayout(SEVEN_TABS);
    fireEvent.click(screen.getByRole("button", { name: /more/i }));

    const sheet = screen.getByRole("menu", { name: "More navigation" });
    expect(within(sheet).getByText("Vendor Hub")).toBeInTheDocument();
    expect(within(sheet).getByText("Communication")).toBeInTheDocument();
    expect(within(sheet).getByText("Users & Access")).toBeInTheDocument();
  });

  it("closes the sheet and reports the selected tab when an overflow item is tapped", () => {
    const onTabChange = vi.fn();
    render(
      <AppLayout user={USER} tabs={SEVEN_TABS} activeTab="projects" onTabChange={onTabChange} onLogout={vi.fn()} onRefresh={vi.fn()}>
        <p>Page content</p>
      </AppLayout>,
    );

    fireEvent.click(screen.getByRole("button", { name: /more/i }));
    fireEvent.click(screen.getByRole("menuitem", { name: /Users & Access/ }));

    expect(onTabChange).toHaveBeenCalledWith("users");
    expect(screen.queryByRole("menu", { name: "More navigation" })).toBeNull();
  });

  it("closes the sheet when the backdrop is clicked, without selecting a tab", () => {
    const onTabChange = vi.fn();
    render(
      <AppLayout user={USER} tabs={SEVEN_TABS} activeTab="projects" onTabChange={onTabChange} onLogout={vi.fn()} onRefresh={vi.fn()}>
        <p>Page content</p>
      </AppLayout>,
    );

    fireEvent.click(screen.getByRole("button", { name: /more/i }));
    fireEvent.click(screen.getByRole("presentation"));

    expect(onTabChange).not.toHaveBeenCalled();
    expect(screen.queryByRole("menu", { name: "More navigation" })).toBeNull();
  });

  it("marks the More button as active when the current tab is one of the overflowed ones", () => {
    renderLayout(SEVEN_TABS, "users");
    const nav = screen.getByRole("navigation", { name: "Mobile navigation" });
    const moreButton = within(nav).getByRole("button", { name: /more/i });
    expect(moreButton.className).toMatch(/bg-slate-950/);
  });
});
