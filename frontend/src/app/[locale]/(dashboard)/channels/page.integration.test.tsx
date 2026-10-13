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

import { toast } from "sonner";

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
    connection: null,
    speech_to_text_provider: null,
    speech_to_text_model: null,
    agents: [{ id: "a1", name: "Support", slug: "support", has_avatar: false }],
    created_at: "2026-08-09T18:00:00Z",
    ...overrides,
  };
}

function serve(bots: ChannelBot[]) {
  // By URL: the dialogs now also fetch the speech-to-text catalog, and a single
  // resolved value would answer that with a list of bots.
  vi.mocked(apiClient.get).mockImplementation(async (path: string) =>
    path.startsWith("/providers/speech-to-text-models")
      ? {
          items: [
            {
              provider: "openai",
              name: "OpenAI",
              models: [
                { id: "whisper-1", name: "Whisper", description: "Widest language coverage." },
              ],
            },
          ],
          total: 1,
        }
      : { items: bots, total: bots.length },
  );
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

  it("warns that a Socket Mode bot has no token to open its socket with", async () => {
    // This asserted "Signing secret" here, on a polling bot, and passed - which
    // is the bug written down as a test. Socket Mode verifies nothing inbound;
    // what it cannot start without is the xapp- token.
    serve([bot({ platform: "slack", api_base_url: null, webhook_mode: false })]);
    await mount();

    expect(await screen.findByText("No app-level token")).toBeVisible();
    expect(screen.queryByText("No signing secret")).toBeNull();
  });

  it("warns that a Slack webhook cannot verify what arrives", async () => {
    // The other transport, and the other credential: without the signing secret
    // the events route answers 500 to everything, the URL challenge included.
    serve([
      bot({
        platform: "slack",
        api_base_url: null,
        webhook_mode: true,
        has_slack_signing_secret: false,
      }),
    ]);
    await mount();

    expect(await screen.findByText("No signing secret")).toBeVisible();
  });

  it("says nothing is missing once a Socket Mode bot has its app token", async () => {
    serve([
      bot({
        platform: "slack",
        api_base_url: null,
        webhook_mode: false,
        has_slack_app_token: true,
        has_slack_signing_secret: false,
      }),
    ]);
    await mount();

    await screen.findByText("Acme Support");
    expect(screen.queryByText("No app-level token")).toBeNull();
    expect(screen.queryByText("No signing secret")).toBeNull();
  });

  it("says out loud that a live bot's connection is down", async () => {
    // The state this exists for: the row showed `Polling`, an agent bound and
    // nothing else, while the reason sat in a container log (#1351).
    serve([
      bot({
        connection: { state: "down", reason: "Add the xapp- token in the bot's settings." },
      }),
    ]);
    await mount();

    expect(await screen.findByText("Not connected")).toBeVisible();
  });

  it("carries the reason where somebody can read it", async () => {
    serve([bot({ connection: { state: "down", reason: "Add the xapp- token." } })]);
    await mount();

    expect(await screen.findByTitle("Add the xapp- token.")).toBeVisible();
  });

  it("says nothing about a connection that is up", async () => {
    serve([bot({ connection: { state: "up", reason: null } })]);
    await mount();

    await screen.findByText("Acme Support");
    expect(screen.queryByText("Not connected")).toBeNull();
  });

  it("says nothing about a connection nobody could report on", async () => {
    // No Redis, or an entry that expired. Unknown is not a fault, and a red
    // badge on every bot would be this defect pointing the other way.
    serve([bot({ connection: null })]);
    await mount();

    await screen.findByText("Acme Support");
    expect(screen.queryByText("Not connected")).toBeNull();
  });

  it("does not call a paused bot disconnected", async () => {
    // It has no connection by design, and the row already says `Paused`.
    serve([bot({ is_active: false, connection: { state: "down", reason: "stopped" } })]);
    await mount();

    expect(await screen.findByText("Paused")).toBeVisible();
    expect(screen.queryByText("Not connected")).toBeNull();
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

  it("adds the app token a Slack bot was registered without", async () => {
    // The flow this dialog exists for: the xapp- token is generated on another
    // Slack screen, minutes after the bot was registered here, and the only way
    // to supply it used to be deleting the bot - which takes its binding too.
    const jarvis = bot({ id: "b9", platform: "slack", name: "Jarvis", api_base_url: null });
    serve([jarvis]);
    vi.mocked(apiClient.patch).mockResolvedValue({ ...jarvis, has_slack_app_token: true });
    await mount();

    await userEvent.click(await screen.findByRole("button", { name: "Edit Jarvis" }));
    await userEvent.type(screen.getByLabelText(/App-level token/), "xapp-1-A0000-abc");
    await userEvent.click(screen.getByRole("button", { name: "Save" }));

    await waitFor(() =>
      expect(apiClient.patch).toHaveBeenCalledWith("/channels/bots/b9", {
        slack_app_token: "xapp-1-A0000-abc",
      }),
    );
  });

  it("keeps the dialog open and says so when the save is refused", async () => {
    // A refused patch must not read as a saved one: the credential is still
    // missing and the operator has to see that it is.
    serve([bot({ platform: "slack", name: "Jarvis", api_base_url: null })]);
    vi.mocked(apiClient.patch).mockRejectedValue(new Error("nope"));
    await mount();

    await userEvent.click(await screen.findByRole("button", { name: "Edit Jarvis" }));
    await userEvent.type(screen.getByLabelText(/App-level token/), "xapp-1-A0000-abc");
    await userEvent.click(screen.getByRole("button", { name: "Save" }));

    await waitFor(() => expect(toast.error).toHaveBeenCalled());
    expect(screen.getByRole("button", { name: "Save" })).toBeVisible();
  });

  it("will not save a dialog nobody edited", async () => {
    // A patch of {} is a write that reseals every stored credential under a new
    // key version for no reason, so there is nothing to send and nothing to do.
    serve([bot({ platform: "slack", name: "Jarvis", api_base_url: null })]);
    await mount();

    await userEvent.click(await screen.findByRole("button", { name: "Edit Jarvis" }));

    expect(screen.getByRole("button", { name: "Save" })).toBeDisabled();
  });

  it("does not offer the platform for editing", async () => {
    // It decides which credentials the row carries and how messages reach it,
    // so changing it is registering a different bot under one id.
    serve([bot({ platform: "slack", name: "Jarvis", api_base_url: null })]);
    await mount();

    await userEvent.click(await screen.findByRole("button", { name: "Edit Jarvis" }));

    expect(screen.queryByRole("button", { name: "Telegram" })).toBeNull();
  });

  it("never puts a stored credential back in the box", async () => {
    // Sealed at rest and never read back, so the input starts empty and says
    // that leaving it empty keeps what is there.
    serve([
      bot({
        platform: "slack",
        name: "Jarvis",
        api_base_url: null,
        has_slack_app_token: true,
      }),
    ]);
    await mount();

    await userEvent.click(await screen.findByRole("button", { name: "Edit Jarvis" }));

    expect(screen.getByLabelText(/App-level token/)).toHaveValue("");
    expect(screen.getAllByText(/Leave blank to keep it/).length).toBeGreaterThan(0);
  });

  it("renames a bot without touching a credential", async () => {
    const acme = bot();
    serve([acme]);
    vi.mocked(apiClient.patch).mockResolvedValue({ ...acme, name: "Acme Ops" });
    await mount();

    await userEvent.click(await screen.findByRole("button", { name: "Edit Acme Support" }));
    await userEvent.clear(screen.getByLabelText(/Name/));
    await userEvent.type(screen.getByLabelText(/Name/), "Acme Ops");
    await userEvent.click(screen.getByRole("button", { name: "Save" }));

    await waitFor(() =>
      expect(apiClient.patch).toHaveBeenCalledWith("/channels/bots/b1", { name: "Acme Ops" }),
    );
  });

  it("refuses a token too short to be one the platform issued", async () => {
    serve([bot({ platform: "slack", name: "Jarvis", api_base_url: null })]);
    await mount();

    await userEvent.click(await screen.findByRole("button", { name: "Edit Jarvis" }));
    await userEvent.type(screen.getByLabelText(/Replace bot token/), "xoxb-1");

    expect(screen.getByRole("button", { name: "Save" })).toBeDisabled();
    expect(screen.getByText(/not one the platform issued/)).toBeVisible();
  });

  it("offers a transcription model for an existing bot", async () => {
    // A voice note is the one attachment an agent cannot be handed as a file, so
    // somebody has to choose what listens to it.
    serve([bot({ platform: "telegram", name: "Jarvis", api_base_url: null })]);
    await mount();

    await userEvent.click(await screen.findByRole("button", { name: "Edit Jarvis" }));

    expect(await screen.findByLabelText(/Voice transcription/)).toBeVisible();
  });

  it("sends both halves of the transcription pair together", async () => {
    // A provider with no model has nothing to call, and the server refuses one
    // alone - so the picker never produces that state.
    const jarvis = bot({ platform: "telegram", name: "Jarvis", api_base_url: null });
    serve([jarvis]);
    vi.mocked(apiClient.patch).mockResolvedValue(jarvis);
    await mount();

    await userEvent.click(await screen.findByRole("button", { name: "Edit Jarvis" }));
    await userEvent.click(await screen.findByLabelText(/Voice transcription/));
    await userEvent.click(await screen.findByRole("option", { name: "OpenAI" }));
    await userEvent.click(screen.getByRole("button", { name: "Save" }));

    await waitFor(() =>
      expect(apiClient.patch).toHaveBeenCalledWith(`/channels/bots/${jarvis.id}`, {
        speech_to_text_provider: "openai",
        speech_to_text_model: "whisper-1",
      }),
    );
  });

  it("clears both halves when transcription is turned off", async () => {
    const listening = bot({
      platform: "telegram",
      name: "Jarvis",
      api_base_url: null,
      speech_to_text_provider: "openai",
      speech_to_text_model: "whisper-1",
    });
    serve([listening]);
    vi.mocked(apiClient.patch).mockResolvedValue(listening);
    await mount();

    await userEvent.click(await screen.findByRole("button", { name: "Edit Jarvis" }));
    await userEvent.click(await screen.findByLabelText(/Voice transcription/));
    await userEvent.click(await screen.findByRole("option", { name: "Do not transcribe" }));
    await userEvent.click(screen.getByRole("button", { name: "Save" }));

    await waitFor(() =>
      expect(apiClient.patch).toHaveBeenCalledWith(`/channels/bots/${listening.id}`, {
        speech_to_text_provider: null,
        speech_to_text_model: null,
      }),
    );
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
