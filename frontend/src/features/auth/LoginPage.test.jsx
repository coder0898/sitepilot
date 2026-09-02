import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { LoginPage } from "./LoginPage";

describe("LoginPage", () => {
  it("always offers Google sign-in", () => {
    render(<LoginPage onGoogle={vi.fn()}/>);
    expect(screen.getByRole("button", { name: /continue with google/i })).toBeInTheDocument();
  });

  it("hides the local dev sign-in panel by default (e.g. against a real deployment)", () => {
    render(<LoginPage onGoogle={vi.fn()}/>);
    expect(screen.queryByText("Local dev sign-in")).not.toBeInTheDocument();
  });

  it("shows the dev panel only when the backend reports it's available, with all five local test accounts", () => {
    render(<LoginPage onGoogle={vi.fn()} devLoginEnabled onDevLogin={vi.fn()}/>);
    expect(screen.getByText("Local dev sign-in")).toBeInTheDocument();
    for (const label of ["Super Admin", "Admin", "Project Manager", "Supervisor", "Internal Employee"]) {
      expect(screen.getByRole("button", { name: label })).toBeInTheDocument();
    }
  });

  it("signs in as a preset account on click", async () => {
    const onDevLogin = vi.fn().mockResolvedValue(undefined);
    render(<LoginPage onGoogle={vi.fn()} devLoginEnabled onDevLogin={onDevLogin}/>);
    fireEvent.click(screen.getByRole("button", { name: "Supervisor" }));
    await waitFor(() => expect(onDevLogin).toHaveBeenCalledWith("deepaks@sitesops.local"));
  });

  it("signs in as any typed email, for testing a brand-new invite's first login", async () => {
    const onDevLogin = vi.fn().mockResolvedValue(undefined);
    render(<LoginPage onGoogle={vi.fn()} devLoginEnabled onDevLogin={onDevLogin}/>);
    fireEvent.change(screen.getByPlaceholderText(/sign in as any email/i), { target: { value: "newpm@test.local" } });
    fireEvent.click(screen.getByRole("button", { name: "Go" }));
    await waitFor(() => expect(onDevLogin).toHaveBeenCalledWith("newpm@test.local"));
  });

  it("disables the preset buttons while a sign-in is in flight", async () => {
    let resolveLogin;
    const onDevLogin = vi.fn(() => new Promise(resolve => { resolveLogin = resolve; }));
    render(<LoginPage onGoogle={vi.fn()} devLoginEnabled onDevLogin={onDevLogin}/>);

    fireEvent.click(screen.getByRole("button", { name: "Admin" }));
    expect(await screen.findByRole("button", { name: "Signing in…" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Project Manager" })).toBeDisabled();

    resolveLogin();
    await waitFor(() => expect(screen.getByRole("button", { name: "Admin" })).not.toBeDisabled());
  });
});
