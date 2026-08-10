import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ChatAccounts } from "./chat-accounts";
import { listLinkedAccounts, unlinkAccount, type LinkedPlace } from "@/lib/channel-link-api";
import { toast } from "sonner";

vi.mock("@/lib/channel-link-api", () => ({
  listLinkedAccounts: vi.fn(),
  unlinkAccount: vi.fn(),
}));
vi.mock("sonner", () => ({ toast: { error: vi.fn() } }));

/**
 * The chat accounts somebody has connected.
 *
 * A link is granted in a chat and spent on a confirmation page, so without this
 * the only record of what was connected is a message that scrolled away - and
 * there was no way to undo it at all.
 */
function account(overrides: Record<string, unknown> = {}) {
  return {
    id: "i-1",
    platform: "mattermost",
    platform_username: "kacper.wlodarczyk",
    platform_display_name: "Kacper",
    is_active: true,
    created_at: "2026-08-09T18:00:00Z",
    places: [] as LinkedPlace[],
    ...overrides,
  };
}

function place(overrides: Partial<LinkedPlace> = {}): LinkedPlace {
  return {
    bot_id: "b-1",
    bot_name: "Acme Support",
    host: "mattermost.acme.com",
    agents: [{ id: "a-1", name: "Support", slug: "support", has_avatar: false }],
    ...overrides,
  };
}

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(listLinkedAccounts).mockResolvedValue([account()]);
  vi.mocked(unlinkAccount).mockResolvedValue(undefined);
});

describe("connected chat accounts", () => {
  it("names the account and the platform it is on", async () => {
    render(<ChatAccounts />);

    expect(await screen.findByText("Kacper")).toBeVisible();
    expect(screen.getByText("Mattermost")).toBeVisible();
  });

  it("falls back to the username when there is no display name", async () => {
    vi.mocked(listLinkedAccounts).mockResolvedValue([account({ platform_display_name: null })]);
    render(<ChatAccounts />);

    expect(await screen.findByText("kacper.wlodarczyk")).toBeVisible();
  });

  it("falls back to the row's own id when the platform named nobody", async () => {
    vi.mocked(listLinkedAccounts).mockResolvedValue([
      account({ platform_display_name: null, platform_username: null }),
    ]);
    render(<ChatAccounts />);

    expect(await screen.findByText("i-1")).toBeVisible();
  });

  it("shows a platform it has no label for rather than nothing", async () => {
    vi.mocked(listLinkedAccounts).mockResolvedValue([account({ platform: "discord" })]);
    render(<ChatAccounts />);

    expect(await screen.findByText("discord")).toBeVisible();
  });

  it("says how to connect one when there are none", async () => {
    vi.mocked(listLinkedAccounts).mockResolvedValue([]);
    render(<ChatAccounts />);

    expect(await screen.findByText(/Message one of your organization's bots/)).toBeVisible();
  });

  it("drops the row it disconnected without refetching", async () => {
    render(<ChatAccounts />);
    await userEvent.click(await screen.findByRole("button", { name: /Disconnect/ }));

    await waitFor(() => expect(screen.queryByText("Kacper")).toBeNull());
    expect(unlinkAccount).toHaveBeenCalledWith("i-1");
  });

  it("keeps the row when disconnecting failed", async () => {
    // Removing it optimistically would say the account is disconnected when the
    // agent will still answer as them.
    vi.mocked(unlinkAccount).mockRejectedValue(new Error("nope"));
    render(<ChatAccounts />);
    await userEvent.click(await screen.findByRole("button", { name: /Disconnect/ }));

    await waitFor(() => expect(toast.error).toHaveBeenCalled());
    expect(screen.getByText("Kacper")).toBeVisible();
  });

  it("names the server the account is on, not only the platform", async () => {
    // "Mattermost" does not say which company's chat this is on a deployment
    // with two Mattermost servers, and the account is keyed on neither.
    vi.mocked(listLinkedAccounts).mockResolvedValue([account({ places: [place()] })]);
    render(<ChatAccounts />);

    expect(await screen.findByText("Acme Support · mattermost.acme.com")).toBeVisible();
  });

  it("names the bot alone where the platform has no server of its own", async () => {
    vi.mocked(listLinkedAccounts).mockResolvedValue([
      account({ platform: "slack", places: [place({ host: null, bot_name: "Acme Slack" })] }),
    ]);
    render(<ChatAccounts />);

    expect(await screen.findByText("Acme Slack")).toBeVisible();
  });

  it("shows which agents answer there", async () => {
    // The reason somebody connected the account at all, and the same handles
    // they would type into the chat.
    vi.mocked(listLinkedAccounts).mockResolvedValue([account({ places: [place()] })]);
    render(<ChatAccounts />);

    expect(await screen.findByText("@support")).toBeVisible();
  });

  it("says so when a bot has nothing this reader can see answering on it", async () => {
    // Not the same as "not used yet", and an empty row would read as one.
    vi.mocked(listLinkedAccounts).mockResolvedValue([account({ places: [place({ agents: [] })] })]);
    render(<ChatAccounts />);

    expect(await screen.findByText(/No agent you can see/)).toBeVisible();
  });

  it("says an account has been connected but never used", async () => {
    render(<ChatAccounts />);

    expect(await screen.findByText(/Not used anywhere yet/)).toBeVisible();
  });

  it("says so when the list itself could not be fetched", async () => {
    // An empty list and a failed request are the same pixels otherwise, and only
    // one of them means "you have connected nothing".
    vi.mocked(listLinkedAccounts).mockRejectedValue(new Error("offline"));
    render(<ChatAccounts />);

    await waitFor(() => expect(toast.error).toHaveBeenCalled());
  });
});
