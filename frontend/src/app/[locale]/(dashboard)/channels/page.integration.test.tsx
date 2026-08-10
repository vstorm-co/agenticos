import type { ReactNode } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import ChannelsPage from "./page";
import { apiClient } from "@/lib/api-client";
import type { ChannelBot } from "@/types/channels";

vi.mock("@/lib/api-client", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/api-client")>();
  return {
    ...actual,
    apiClient: { get: vi.fn(), post: vi.fn(), patch: vi.fn(), delete: vi.fn() },
  };
});
vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));

const permissions = { can: vi.fn(() => true) };
vi.mock("@/hooks/use-permissions", () => ({ usePermissions: () => permissions }));

function wrapper({ children }: { children: ReactNode }) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

function bot(overrides: Partial<ChannelBot> = {}): ChannelBot {
  return {
    id: "b1",
    platform: "mattermost",
    name: "Acme Support",
    is_active: true,
    webhook_mode: false,
    webhook_url: null,
    api_base_url: "https://mattermost.acme.com",
    has_webhook_secret: true,
    has_slack_signing_secret: false,
    has_slack_app_token: false,
    agents: [{ id: "a1", name: "Support", slug: "support", has_avatar: false }],
    created_at: "2026-08-09T18:00:00Z",
    ...overrides,
  };
}

function serve(bots: ChannelBot[]) {
  vi.mocked(apiClient.get).mockResolvedValue({ items: bots, total: bots.length });
}

async function mount() {
  render(<ChannelsPage />, { wrapper });
  await waitFor(() => expect(apiClient.get).toHaveBeenCalled());
}

beforeEach(() => {
  vi.clearAllMocks();
  permissions.can.mockReturnValue(true);
});

describe("the channels page", () => {
  it("names each bot and the server it lives on", async () => {
    // "Mattermost" does not say which of them on a deployment with two.
    serve([bot()]);
    await mount();

    expect(await screen.findByText("Acme Support")).toBeVisible();
    expect(screen.getByText("Mattermost · https://mattermost.acme.com")).toBeVisible();
  });

  it("names the agents that answer there", async () => {
    serve([bot()]);
    await mount();

    expect(await screen.findByText("@support")).toBeVisible();
  });

  it("says out loud that a bot nobody bound answers nothing", async () => {
    // Registered, live, and silent - which from a chat window is
    // indistinguishable from broken, and is why this column exists.
    serve([bot({ agents: [] })]);
    await mount();

    expect(await screen.findByText(/No agent bound/)).toBeVisible();
  });

  it("warns that a Slack bot cannot verify what arrives", async () => {
    serve([bot({ platform: "slack", api_base_url: null, has_slack_signing_secret: false })]);
    await mount();

    expect(await screen.findByText("Signing secret")).toBeVisible();
  });

  it("warns that a Mattermost webhook has no token to check", async () => {
    serve([bot({ webhook_mode: true, has_webhook_secret: false })]);
    await mount();

    expect(await screen.findByText("No webhook token")).toBeVisible();
  });

  it("says a paused bot is paused rather than showing nothing", async () => {
    serve([bot({ is_active: false })]);
    await mount();

    expect(await screen.findByText("Paused")).toBeVisible();
  });

  it("says how to get started when there are no channels", async () => {
    serve([]);
    await mount();

    expect(await screen.findByText("No channel registered yet")).toBeVisible();
  });

  it("registers a Mattermost bot from the dialog", async () => {
    serve([]);
    vi.mocked(apiClient.post).mockResolvedValue(bot());
    await mount();

    await userEvent.click(await screen.findByRole("button", { name: "Register a channel" }));
    await userEvent.type(screen.getByLabelText(/Name/), "Acme Support");
    await userEvent.type(screen.getByLabelText(/Bot token/), "a-long-enough-token");
    await userEvent.type(screen.getByLabelText(/Server URL/), "https://mattermost.acme.com");
    await userEvent.click(screen.getByRole("button", { name: "Register" }));

    await waitFor(() =>
      expect(apiClient.post).toHaveBeenCalledWith("/channels/bots", {
        platform: "mattermost",
        name: "Acme Support",
        token: "a-long-enough-token",
        api_base_url: "https://mattermost.acme.com",
      }),
    );
  });

  it("will not register a Mattermost bot without its server", async () => {
    // Mattermost is self-hosted: a bot that does not know its server cannot
    // reply, and the backend refuses to save one. Said before the round trip.
    serve([]);
    await mount();

    await userEvent.click(await screen.findByRole("button", { name: "Register a channel" }));
    await userEvent.type(screen.getByLabelText(/Name/), "Acme Support");
    await userEvent.type(screen.getByLabelText(/Bot token/), "a-long-enough-token");

    expect(screen.getByRole("button", { name: "Register" })).toBeDisabled();
  });

  it("asks a Slack bot for its own credentials instead", async () => {
    serve([]);
    await mount();

    await userEvent.click(await screen.findByRole("button", { name: "Register a channel" }));
    await userEvent.click(screen.getByRole("button", { name: "Slack" }));

    expect(screen.getByLabelText(/Signing secret/)).toBeVisible();
    expect(screen.queryByLabelText(/Server URL/)).toBeNull();
  });

  it("keeps a half-typed Mattermost server out of a Slack registration", async () => {
    // Switching platform asks other questions, so the answers to the old ones
    // go - otherwise a Slack bot is posted with a Mattermost address on it.
    serve([]);
    vi.mocked(apiClient.post).mockResolvedValue(bot());
    await mount();

    await userEvent.click(await screen.findByRole("button", { name: "Register a channel" }));
    await userEvent.type(screen.getByLabelText(/Server URL/), "https://mattermost.acme.com");
    await userEvent.click(screen.getByRole("button", { name: "Slack" }));
    await userEvent.type(screen.getByLabelText(/Name/), "Acme Slack");
    await userEvent.type(screen.getByLabelText(/Bot token/), "xoxb-a-long-token");
    await userEvent.click(screen.getByRole("button", { name: "Register" }));

    await waitFor(() =>
      expect(apiClient.post).toHaveBeenCalledWith("/channels/bots", {
        platform: "slack",
        name: "Acme Slack",
        token: "xoxb-a-long-token",
      }),
    );
  });

  it("pauses a bot without touching anything else about it", async () => {
    serve([bot()]);
    vi.mocked(apiClient.post).mockResolvedValue(bot({ is_active: false }));
    await mount();

    await userEvent.click(await screen.findByRole("button", { name: "Pause Acme Support" }));

    expect(apiClient.post).toHaveBeenCalledWith("/channels/bots/b1/deactivate", {});
  });

  it("says nothing here about what a turn costs", async () => {
    // That is the agent author's decision about this surface, so it lives under
    // the binding in the Builder. On this page it was an operator's setting in
    // a table of servers and tokens, next to nothing else about the agent.
    serve([bot()]);
    await mount();

    await screen.findByText("Acme Support");
    expect(screen.queryByRole("combobox", { name: /Cost reporting/ })).toBeNull();
  });

  it("removes a bot", async () => {
    serve([bot()]);
    vi.mocked(apiClient.delete).mockResolvedValue(undefined);
    await mount();

    await userEvent.click(await screen.findByRole("button", { name: "Remove Acme Support" }));

    expect(apiClient.delete).toHaveBeenCalledWith("/channels/bots/b1");
  });

  it("does not ask for the list at all without channels:manage", async () => {
    // The backend gates the listing on it, so fetching would put a 403 in the
    // network log of every member who visits the page.
    permissions.can.mockReturnValue(false);
    serve([]);
    render(<ChannelsPage />, { wrapper });

    expect(await screen.findByText(/channels:manage/)).toBeVisible();
    expect(apiClient.get).not.toHaveBeenCalled();
  });
});
