import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { ProfileModal } from "./CommunicationDirectory";

const categories = [{ id: "cat-1", name: "Electrical", parent_id: null, active: true }];
const vendor = { id: "v1", name: "Test Electric Co.", status: "active", category_ids: ["cat-1"] };

describe("ProfileModal save button (footer slot, not the old sticky-inside-scroll button)", () => {
  it("submits the vendor form via the button's form= attribute, even though the button lives outside the <form>", async () => {
    const onSubmit = vi.fn(event => event.preventDefault());
    render(<ProfileModal vendor={vendor} categories={categories} onClose={vi.fn()} onSubmit={onSubmit}/>);

    const saveButton = screen.getByRole("button", { name: "Save vendor changes" });
    const form = document.getElementById("vendor-profile-form");
    // Confirms the fix's core mechanism: the button is NOT a DOM descendant
    // of the form (proving it's a real footer, not the old in-form sticky
    // button) yet is still wired to submit it.
    expect(form.contains(saveButton)).toBe(false);
    expect(saveButton.getAttribute("form")).toBe("vendor-profile-form");

    fireEvent.click(saveButton);

    expect(onSubmit).toHaveBeenCalledTimes(1);
  });
});
