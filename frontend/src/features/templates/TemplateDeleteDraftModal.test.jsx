import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { templatesApi } from "../../api/templatesApi";
import { TemplateDeleteDraftModal } from "./components/TemplateDeleteDraftModal";

vi.mock("../../api/templatesApi", () => ({
  templatesApi: {
    getVersion: vi.fn(),
    deleteDraftVersion: vi.fn(),
  },
}));

const listDraft = {
  version_id: "draft-2",
  version_no: 2,
  status: "draft",
};

beforeEach(() => {
  vi.clearAllMocks();
  templatesApi.getVersion.mockResolvedValue({ ...listDraft, revision_token: "rev-current" });
  templatesApi.deleteDraftVersion.mockResolvedValue({ deleted: true, template_deleted: false });
});

describe("TemplateDeleteDraftModal", () => {
  it("loads the current revision before deleting a draft opened from the version list", async () => {
    const onSuccess = vi.fn();
    render(<TemplateDeleteDraftModal version={listDraft} onClose={vi.fn()} onSuccess={onSuccess} />);

    fireEvent.change(screen.getByLabelText("Draft deletion reason"), { target: { value: "Remove test draft" } });
    fireEvent.change(screen.getByLabelText("Type DELETE to confirm"), { target: { value: "DELETE" } });
    fireEvent.click(screen.getByRole("button", { name: /delete draft/i }));

    await waitFor(() => expect(templatesApi.getVersion).toHaveBeenCalledWith("draft-2"));
    expect(templatesApi.deleteDraftVersion).toHaveBeenCalledWith("draft-2", {
      revision_token: "rev-current",
      reason: "Remove test draft",
    });
    expect(onSuccess).toHaveBeenCalled();
  });

  it("renders structured API messages instead of object Object", async () => {
    templatesApi.deleteDraftVersion.mockRejectedValue({
      message: { code: "stale_revision", message: "The draft changed. Reload and retry." },
      details: { detail: { code: "stale_revision", message: "The draft changed. Reload and retry." } },
    });
    render(<TemplateDeleteDraftModal version={{ ...listDraft, revision_token: "stale" }} onClose={vi.fn()} onSuccess={vi.fn()} />);

    fireEvent.change(screen.getByLabelText("Draft deletion reason"), { target: { value: "Remove test draft" } });
    fireEvent.change(screen.getByLabelText("Type DELETE to confirm"), { target: { value: "DELETE" } });
    fireEvent.click(screen.getByRole("button", { name: /delete draft/i }));

    expect(await screen.findByText("The draft changed. Reload and retry.")).toBeInTheDocument();
    expect(screen.queryByText("[object Object]")).not.toBeInTheDocument();
  });
});
