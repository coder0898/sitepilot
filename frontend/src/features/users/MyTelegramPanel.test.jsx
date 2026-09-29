import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { telegramConnectApi } from "../../api/telegramConnectApi";
import { MyTelegramPanel } from "./components/MyTelegramPanel";

vi.mock("../../api/telegramConnectApi", () => ({
  telegramConnectApi: { myStatus: vi.fn(), generateMyCode: vi.fn(), unlinkMe: vi.fn() },
}));

const link = "https://t.me/SiteOpsBot?start=abc";

beforeEach(() => {
  vi.clearAllMocks();
  Object.assign(navigator, { clipboard: { writeText: vi.fn().mockResolvedValue(undefined) } });
});

describe("My Profile Telegram", () => {
  it("connects through the bot link and shows Connected when the person comes back", async () => {
    telegramConnectApi.myStatus
      .mockResolvedValueOnce({ telegram_connected: false, telegram_chat_hint: null })
      .mockResolvedValueOnce({ telegram_connected: true, telegram_chat_hint: "•••7001" });
    telegramConnectApi.generateMyCode.mockResolvedValue({
      code: "abc", link, start_command: "/start abc", expires_at: new Date(Date.now() + 900000).toISOString(),
    });
    render(<MyTelegramPanel/>);
    expect(await screen.findByText("Not connected")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /connect telegram/i }));
    const open = await screen.findByRole("link", { name: /open telegram/i });
    expect(open).toHaveAttribute("href", link);
    // The request names nobody - the backend uses the session.
    expect(telegramConnectApi.generateMyCode).toHaveBeenCalledWith();

    fireEvent.click(screen.getByRole("button", { name: /copy link/i }));
    await waitFor(() => expect(navigator.clipboard.writeText).toHaveBeenCalledWith(link));

    await act(async () => { window.dispatchEvent(new Event("focus")); });
    expect(await screen.findByText("Connected · chat •••7001")).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: /open telegram/i })).not.toBeInTheDocument();
  });

  it("shows why a link can't be made (already linked)", async () => {
    telegramConnectApi.myStatus.mockResolvedValue({ telegram_connected: false });
    telegramConnectApi.generateMyCode.mockRejectedValue(new Error("This person is already linked to Telegram. Unlink it first."));
    render(<MyTelegramPanel/>);
    fireEvent.click(await screen.findByRole("button", { name: /connect telegram/i }));
    expect(await screen.findByText(/already linked to Telegram/i)).toBeInTheDocument();
  });

  it("lets a connected person disconnect their own Telegram after confirming", async () => {
    vi.spyOn(window, "confirm").mockReturnValue(true);
    telegramConnectApi.myStatus.mockResolvedValue({ telegram_connected: true, telegram_chat_hint: "•••7001" });
    telegramConnectApi.unlinkMe.mockResolvedValue({ telegram_connected: false, telegram_chat_hint: null });
    render(<MyTelegramPanel/>);
    fireEvent.click(await screen.findByRole("button", { name: /disconnect telegram/i }));
    await waitFor(() => expect(telegramConnectApi.unlinkMe).toHaveBeenCalledWith());
    expect(await screen.findByText("Not connected")).toBeInTheDocument();
  });

  it("stays hidden for an account with no employee profile", async () => {
    telegramConnectApi.myStatus.mockRejectedValue(new Error("Your account has no employee profile to link Telegram to."));
    const { container } = render(<MyTelegramPanel/>);
    await waitFor(() => expect(telegramConnectApi.myStatus).toHaveBeenCalled());
    expect(container).toBeEmptyDOMElement();
  });
});
