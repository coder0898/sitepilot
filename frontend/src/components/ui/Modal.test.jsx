import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { Modal } from "./Modal";

describe("Modal footer", () => {
  it("renders the footer as a sibling of the scrollable body, not inside it", () => {
    render(<Modal title="Test" onClose={vi.fn()} footer={<button>Save</button>}>
      <p>Body content</p>
    </Modal>);

    const dialog = screen.getByRole("dialog", { name: "Test" });
    const footerButton = screen.getByRole("button", { name: "Save" });
    const bodyText = screen.getByText("Body content");

    // The footer button must not be a descendant of the scrollable body
    // container - it needs to be a true flex sibling (fixed at the bottom
    // of the dialog) rather than living inside the `overflow-y-auto`
    // element, which is what made the vendor-edit modal's old sticky
    // footer button drift out of place once its content grew.
    const scrollableBody = bodyText.closest(".overflow-y-auto");
    expect(scrollableBody).not.toBeNull();
    expect(scrollableBody.contains(footerButton)).toBe(false);
    expect(dialog.contains(footerButton)).toBe(true);
  });

  it("renders no footer element when none is given (backward compatible)", () => {
    const { container } = render(<Modal title="No footer" onClose={vi.fn()}><p>Content</p></Modal>);
    expect(container.querySelector("footer")).toBeNull();
  });
});

describe("Modal background scroll lock", () => {
  it("locks body scroll while mounted and restores it on unmount", () => {
    document.body.style.overflow = "";
    const { unmount } = render(<Modal title="Locked" onClose={vi.fn()}><p>Content</p></Modal>);

    expect(document.body.style.overflow).toBe("hidden");

    unmount();

    expect(document.body.style.overflow).toBe("");
  });

  it("restores the page's PRE-EXISTING overflow value, not just an empty string", () => {
    document.body.style.overflow = "scroll";
    const { unmount } = render(<Modal title="Locked" onClose={vi.fn()}><p>Content</p></Modal>);

    expect(document.body.style.overflow).toBe("hidden");

    unmount();

    expect(document.body.style.overflow).toBe("scroll");
    document.body.style.overflow = "";
  });
});
