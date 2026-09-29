import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { telegramConnectApi } from "../../api/telegramConnectApi";
import { UserModal } from "./components/UserModals";

vi.mock("../../api/usersApi", () => ({ usersApi: { events: vi.fn().mockResolvedValue([]) } }));
vi.mock("../../api/channelToggleApi", () => ({ channelToggleApi: { toggle: vi.fn() } }));
vi.mock("../../api/telegramConnectApi", () => ({ telegramConnectApi: { generateCode: vi.fn(), unlink: vi.fn(), myStatus: vi.fn(), generateMyCode: vi.fn() } }));

function person(profile) {
  return {
    id: "u1", name: "Rohan", email: "rohan@example.com", role: "supervisor", active: true, phone: "",
    activation_status: "active",
    employee_profile: { id: "p1", employee_code: "E-1", designation: "Supervisor", active_channel: "telegram", ...profile },
  };
}

function renderModal(profile) {
  return render(<UserModal
    selectedUser={person(profile)} actor={{ role: "admin" }} catalog={[]} manageableRoles={["supervisor"]}
    onClose={vi.fn()} action={vi.fn()}
  />);
}

beforeEach(() => {
  vi.clearAllMocks();
  Object.assign(navigator, { clipboard: { writeText: vi.fn().mockResolvedValue(undefined) } });
});

describe("Telegram link in User Management", () => {
  it("generates a one-time bot link and copies it", async () => {
    telegramConnectApi.generateCode.mockResolvedValue({
      code: "abc", start_command: "/start abc", link: "https://t.me/SiteOpsBot?start=abc",
      expires_at: new Date(Date.now() + 15 * 60000).toISOString(),
    });
    renderModal({ telegram_connected: false, telegram_chat_hint: null });
    expect(screen.getByText("Telegram not connected")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /generate link/i }));
    expect(await screen.findByText("https://t.me/SiteOpsBot?start=abc")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /copy link/i }));
    await waitFor(() => expect(navigator.clipboard.writeText).toHaveBeenCalledWith("https://t.me/SiteOpsBot?start=abc"));
    expect(await screen.findByRole("button", { name: /copied/i })).toBeInTheDocument();
  });

  it("falls back to the typed /start command when the bot link is unavailable", async () => {
    telegramConnectApi.generateCode.mockResolvedValue({
      code: "abc", start_command: "/start abc", link: null, expires_at: new Date().toISOString(),
    });
    renderModal({ telegram_connected: false });
    fireEvent.click(screen.getByRole("button", { name: /generate link/i }));
    expect(await screen.findByText("/start abc")).toBeInTheDocument();
  });

  it("shows the linked chat and lets an Admin unlink it", async () => {
    vi.spyOn(window, "confirm").mockReturnValue(true);
    telegramConnectApi.unlink.mockResolvedValue({ telegram_connected: false });
    renderModal({ telegram_connected: true, telegram_chat_hint: "•••7001" });
    expect(screen.getByText("Telegram connected · chat •••7001")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /generate link/i })).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /unlink telegram/i }));
    await waitFor(() => expect(telegramConnectApi.unlink).toHaveBeenCalledWith("p1"));
    expect(await screen.findByText("Telegram not connected")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /generate link/i })).toBeInTheDocument();
  });

  it("lets an Admin connect their own Telegram from their own read-only record", async () => {
    telegramConnectApi.myStatus.mockResolvedValue({ telegram_connected: false, telegram_chat_hint: null });
    const admin = { ...person({ telegram_connected: false }), id: "admin-1", role: "admin" };
    render(<UserModal selectedUser={admin} actor={admin} catalog={[]} manageableRoles={["supervisor"]} onClose={vi.fn()} action={vi.fn()}/>);
    expect(await screen.findByRole("button", { name: /connect telegram/i })).toBeInTheDocument();
    expect(screen.getByText(/This is your own account/)).toBeInTheDocument();
  });

  it("does not offer self-linking on someone else's read-only record", async () => {
    const other = { ...person({}), id: "admin-2", role: "admin" };
    render(<UserModal selectedUser={other} actor={{ id: "admin-1", role: "admin" }} catalog={[]} manageableRoles={["supervisor"]} onClose={vi.fn()} action={vi.fn()}/>);
    expect(screen.getByText(/falls outside your management authority/)).toBeInTheDocument();
    expect(telegramConnectApi.myStatus).not.toHaveBeenCalled();
  });
});
