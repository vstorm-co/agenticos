import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ChannelBotsPanel } from "./channel-bots-panel";
import type { ChannelBot } from "@/types/channels";

/**
 * The organization's channel bots.
 *
 * Two things here are worth pinning. The token is **write-only** - sent once at
 * registration, encrypted on arrival, never read back - so the form must never
 * be populated from a bot and the type must be `password`. And a Slack bot
 * without a signing secret cannot verify inbound events, so its webhook refuses
 * everything: the badge saying so is the difference between a five-minute fix and
 * an afternoon debugging a silent bot.
 */

const state = {
  bots: [] as ChannelBot[],
  isLoading: false,
  create: { mutateAsync: vi.fn(), isPending: false },
  setActive: { mutate: vi.fn(), isPending: false },
  setUsageReporting: { mutate: vi.fn(), isPending: false },
  remove: { mutate: vi.fn(), isPending: false },
};

vi.mock("@/hooks", () => ({ useChannelBots: () => state }));

function bot(overrides: Partial<ChannelBot> = {}): ChannelBot {
  return {
    id: "b-1",
    platform: "telegram",
    name: "Support bot",
    is_active: true,
    webhook_mode: true,
    webhook_url: "https://app.test/hook",
    api_base_url: null,
    has_webhook_secret: false,
    has_slack_signing_secret: false,
    has_slack_app_token: false,
    usage_reporting: { mode: "near_limit", near_limit_percent: 80, every_n: 10 },
    created_at: "2026-07-30T10:00:00Z",
    ...overrides,
  };
}

beforeEach(() => {
  state.bots = [];
  state.isLoading = false;
  state.create = { mutateAsync: vi.fn().mockResolvedValue(undefined), isPending: false };
  state.setActive = { mutate: vi.fn(), isPending: false };
  state.remove = { mutate: vi.fn(), isPending: false };
});

async function pickPlatform(label: string) {
  await userEvent.click(screen.getByLabelText("Platform"));
  await userEvent.click(screen.getByRole("option", { name: label }));
}

describe("the channel bots panel", () => {
  it("renders nothing at all to somebody who may not manage channels", () => {
    // Not a disabled form: a bot is an organization resource, and somebody
    // without `channels:manage` has no business seeing the register form.
    const { container } = render(<ChannelBotsPanel canManage={false} />);

    expect(container).toBeEmptyDOMElement();
  });

  it("says the token is encrypted on arrival and never shown again", () => {
    render(<ChannelBotsPanel canManage />);

    expect(screen.getByText(/never shown again/)).toBeInTheDocument();
  });

  it("explains that registering is per workspace and binding is per agent", () => {
    // The confusion this panel exists inside: it renders in the Builder but a
    // bot is not the agent's.
    render(<ChannelBotsPanel canManage />);

    expect(screen.getByText(/registering is once per workspace/)).toBeInTheDocument();
  });

  it("says what to do next when no bot is registered", () => {
    render(<ChannelBotsPanel canManage />);

    expect(screen.getByText(/No bots yet/)).toBeInTheDocument();
  });

  it("says nothing about being empty while it is still loading", () => {
    state.isLoading = true;
    render(<ChannelBotsPanel canManage />);

    expect(screen.queryByText(/No bots yet/)).toBeNull();
  });
});

describe("an existing bot", () => {
  it("names its platform and itself", () => {
    state.bots = [bot()];
    render(<ChannelBotsPanel canManage />);

    expect(screen.getByText("Telegram - Support bot")).toBeInTheDocument();
  });

  it("falls back to the raw platform for one this build does not label", () => {
    // A bot registered by a newer deployment, read by an older frontend.
    state.bots = [bot({ platform: "discord" as ChannelBot["platform"] })];
    render(<ChannelBotsPanel canManage />);

    expect(screen.getByText("discord - Support bot")).toBeInTheDocument();
  });

  it("says whether it is on a webhook or polling", () => {
    state.bots = [bot({ webhook_mode: false })];
    render(<ChannelBotsPanel canManage />);

    expect(screen.getByText("Polling")).toBeInTheDocument();
  });

  it("warns that a Slack bot with no signing secret cannot verify anything", () => {
    // Its webhook refuses every inbound event, silently.
    state.bots = [bot({ platform: "slack", has_slack_signing_secret: false })];
    render(<ChannelBotsPanel canManage />);

    expect(screen.getByText("no signing secret")).toBeInTheDocument();
  });

  it("says nothing about signing secrets for a Slack bot that has one", () => {
    state.bots = [bot({ platform: "slack", has_slack_signing_secret: true })];
    render(<ChannelBotsPanel canManage />);

    expect(screen.queryByText("no signing secret")).toBeNull();
  });

  it("does not warn about signing secrets on a platform that has none", () => {
    state.bots = [bot({ platform: "telegram", has_slack_signing_secret: false })];
    render(<ChannelBotsPanel canManage />);

    expect(screen.queryByText("no signing secret")).toBeNull();
  });

  it("marks a deactivated bot", () => {
    state.bots = [bot({ is_active: false })];
    render(<ChannelBotsPanel canManage />);

    expect(screen.getByText("inactive")).toBeInTheDocument();
  });

  it("deactivates a live bot", async () => {
    state.bots = [bot()];
    render(<ChannelBotsPanel canManage />);

    await userEvent.click(screen.getByRole("button", { name: "Deactivate Support bot" }));

    expect(state.setActive.mutate).toHaveBeenCalledWith({ botId: "b-1", isActive: false });
  });

  it("reactivates a paused bot", async () => {
    state.bots = [bot({ is_active: false })];
    render(<ChannelBotsPanel canManage />);

    await userEvent.click(screen.getByRole("button", { name: "Activate Support bot" }));

    expect(state.setActive.mutate).toHaveBeenCalledWith({ botId: "b-1", isActive: true });
  });

  it("removes the bot it names", async () => {
    state.bots = [bot()];
    render(<ChannelBotsPanel canManage />);

    await userEvent.click(screen.getByRole("button", { name: "Remove Support bot" }));

    expect(state.remove.mutate).toHaveBeenCalledWith("b-1");
  });

  it("stops a second activation toggle while one is in flight", () => {
    state.bots = [bot()];
    state.setActive = { mutate: vi.fn(), isPending: true };
    render(<ChannelBotsPanel canManage />);

    expect(screen.getByRole("button", { name: "Deactivate Support bot" })).toBeDisabled();
  });

  it("stops a second removal while one is in flight", () => {
    state.bots = [bot()];
    state.remove = { mutate: vi.fn(), isPending: true };
    render(<ChannelBotsPanel canManage />);

    expect(screen.getByRole("button", { name: "Remove Support bot" })).toBeDisabled();
  });
});

describe("registering a bot", () => {
  it("keeps the token out of the DOM as readable text", () => {
    // Write-only: it is sent once and never read back, so the field it is typed
    // into must not be a plain text input somebody screenshots.
    render(<ChannelBotsPanel canManage />);

    expect(screen.getByLabelText("Bot token")).toHaveAttribute("type", "password");
  });

  it("says what to paste, per platform", async () => {
    // The one thing people get stuck on.
    render(<ChannelBotsPanel canManage />);

    expect(screen.getByLabelText("Bot token")).toHaveAttribute(
      "placeholder",
      expect.stringContaining("BotFather"),
    );

    await pickPlatform("Slack");

    expect(screen.getByLabelText("Bot token")).toHaveAttribute(
      "placeholder",
      expect.stringContaining("xoxb-"),
    );
  });

  it("refuses to register without a name", async () => {
    render(<ChannelBotsPanel canManage />);

    await userEvent.type(screen.getByLabelText("Bot token"), "1234567890123");

    expect(screen.getByRole("button", { name: "Register" })).toBeDisabled();
  });

  it("refuses a token too short to be a real one", async () => {
    render(<ChannelBotsPanel canManage />);

    await userEvent.type(screen.getByLabelText("Name"), "Support bot");
    await userEvent.type(screen.getByLabelText("Bot token"), "short");

    expect(screen.getByRole("button", { name: "Register" })).toBeDisabled();
  });

  it("registers a Telegram bot with a trimmed name and token", async () => {
    render(<ChannelBotsPanel canManage />);

    await userEvent.type(screen.getByLabelText("Name"), "  Support bot  ");
    await userEvent.type(screen.getByLabelText("Bot token"), "  1234567890123  ");
    await userEvent.click(screen.getByRole("button", { name: "Register" }));

    expect(state.create.mutateAsync).toHaveBeenCalledWith({
      platform: "telegram",
      name: "Support bot",
      token: "1234567890123",
    });
  });

  it("clears the form after a successful registration", async () => {
    // Leaving a token behind invites a second bot with the same credential.
    render(<ChannelBotsPanel canManage />);

    await userEvent.type(screen.getByLabelText("Name"), "Support bot");
    await userEvent.type(screen.getByLabelText("Bot token"), "1234567890123");
    await userEvent.click(screen.getByRole("button", { name: "Register" }));

    expect(screen.getByLabelText("Name")).toHaveValue("");
    expect(screen.getByLabelText("Bot token")).toHaveValue("");
  });

  it("asks for Slack's own credentials only when Slack is chosen", async () => {
    // Each Slack bot is its own Slack app, so it carries its own signing secret
    // and app token. Telegram has neither.
    render(<ChannelBotsPanel canManage />);

    expect(screen.queryByLabelText("Signing secret")).toBeNull();

    await pickPlatform("Slack");

    expect(screen.getByLabelText("Signing secret")).toBeInTheDocument();
    expect(screen.getByLabelText("App-level token (optional)")).toBeInTheDocument();
  });

  it("keeps Slack's extra credentials out of the DOM as readable text too", async () => {
    render(<ChannelBotsPanel canManage />);
    await pickPlatform("Slack");

    expect(screen.getByLabelText("Signing secret")).toHaveAttribute("type", "password");
    expect(screen.getByLabelText("App-level token (optional)")).toHaveAttribute("type", "password");
  });

  it("sends Slack's credentials when they are given", async () => {
    render(<ChannelBotsPanel canManage />);
    await pickPlatform("Slack");

    await userEvent.type(screen.getByLabelText("Name"), "Slack bot");
    await userEvent.type(screen.getByLabelText("Bot token"), "xoxb-1234567890");
    await userEvent.type(screen.getByLabelText("Signing secret"), "sign-me");
    await userEvent.type(screen.getByLabelText("App-level token (optional)"), "xapp-1");
    await userEvent.click(screen.getByRole("button", { name: "Register" }));

    expect(state.create.mutateAsync).toHaveBeenCalledWith({
      platform: "slack",
      name: "Slack bot",
      token: "xoxb-1234567890",
      slack_signing_secret: "sign-me",
      slack_app_token: "xapp-1",
    });
  });

  it("omits Slack's optional credentials rather than sending them empty", async () => {
    // Absent, not `""` - the same bargain the token itself makes. An empty
    // signing secret would be stored and then fail every verification.
    render(<ChannelBotsPanel canManage />);
    await pickPlatform("Slack");

    await userEvent.type(screen.getByLabelText("Name"), "Slack bot");
    await userEvent.type(screen.getByLabelText("Bot token"), "xoxb-1234567890");
    await userEvent.click(screen.getByRole("button", { name: "Register" }));

    expect(state.create.mutateAsync).toHaveBeenCalledWith({
      platform: "slack",
      name: "Slack bot",
      token: "xoxb-1234567890",
    });
  });

  it("does not send Slack's credentials for a non-Slack bot", async () => {
    // Typed under Slack, then the platform changed. The fields keep their values
    // but must not travel.
    render(<ChannelBotsPanel canManage />);
    await pickPlatform("Slack");
    await userEvent.type(screen.getByLabelText("Signing secret"), "sign-me");
    await pickPlatform("Telegram");

    await userEvent.type(screen.getByLabelText("Name"), "Telegram bot");
    await userEvent.type(screen.getByLabelText("Bot token"), "1234567890123");
    await userEvent.click(screen.getByRole("button", { name: "Register" }));

    expect(state.create.mutateAsync).toHaveBeenCalledWith({
      platform: "telegram",
      name: "Telegram bot",
      token: "1234567890123",
    });
  });

  it("offers Mattermost too", async () => {
    render(<ChannelBotsPanel canManage />);

    await pickPlatform("Mattermost");

    expect(screen.getByLabelText("Bot token")).toHaveAttribute(
      "placeholder",
      expect.stringContaining("bot account"),
    );
  });

  it("stops a second registration while one is in flight", async () => {
    state.create = { mutateAsync: vi.fn(), isPending: true };
    render(<ChannelBotsPanel canManage />);

    await userEvent.type(screen.getByLabelText("Name"), "Support bot");
    await userEvent.type(screen.getByLabelText("Bot token"), "1234567890123");

    expect(screen.getByRole("button", { name: "Register" })).toBeDisabled();
  });
});

describe("what a bot says about what a turn cost", () => {
  it("offers the four modes, because a footer on every reply is noise", async () => {
    // And silence is worse: a bot that stops answering on a budget cap looks
    // broken unless somebody said so beforehand.
    state.bots = [bot()];
    render(<ChannelBotsPanel canManage />);

    await userEvent.click(screen.getByRole("combobox", { name: "Usage reporting on Support bot" }));

    expect(screen.getByRole("option", { name: "usage: log only" })).toBeVisible();
    expect(screen.getByRole("option", { name: /near a limit/ })).toBeVisible();
    expect(screen.getByRole("option", { name: /every 10 messages/ })).toBeVisible();
    expect(screen.getByRole("option", { name: /every reply/ })).toBeVisible();
  });

  it("changes the mode and keeps the thresholds it was not asked about", async () => {
    state.bots = [bot({ usage_reporting: { mode: "off", near_limit_percent: 65, every_n: 5 } })];
    render(<ChannelBotsPanel canManage />);

    await userEvent.click(screen.getByRole("combobox", { name: "Usage reporting on Support bot" }));
    await userEvent.click(screen.getByRole("option", { name: /every reply/ }));

    expect(state.setUsageReporting.mutate).toHaveBeenCalledWith({
      botId: "b-1",
      usageReporting: { mode: "always", near_limit_percent: 65, every_n: 5 },
    });
  });

  it("waits rather than queueing a second change", async () => {
    state.bots = [bot()];
    state.setUsageReporting.isPending = true;
    render(<ChannelBotsPanel canManage />);

    expect(screen.getByRole("combobox", { name: "Usage reporting on Support bot" })).toBeDisabled();
    state.setUsageReporting.isPending = false;
  });

  it("sends a Mattermost bot its server and the token Mattermost generated", async () => {
    render(<ChannelBotsPanel canManage />);
    await pickPlatform("Mattermost");

    await userEvent.type(screen.getByLabelText("Name"), "Ops bot");
    await userEvent.type(screen.getByLabelText("Bot token"), "mm-1234567890");
    await userEvent.type(screen.getByLabelText("Server URL"), "https://mattermost.acme.internal");
    await userEvent.type(screen.getByLabelText("Webhook token (optional)"), "from-mattermost");
    await userEvent.click(screen.getByRole("button", { name: "Register" }));

    expect(state.create.mutateAsync).toHaveBeenCalledWith({
      platform: "mattermost",
      name: "Ops bot",
      token: "mm-1234567890",
      api_base_url: "https://mattermost.acme.internal",
      webhook_secret: "from-mattermost",
    });
  });

  it("omits the webhook token rather than sending it empty", async () => {
    // A bot on the event stream needs no token at all, and an empty one would
    // be stored and then fail every verification.
    render(<ChannelBotsPanel canManage />);
    await pickPlatform("Mattermost");

    await userEvent.type(screen.getByLabelText("Name"), "Ops bot");
    await userEvent.type(screen.getByLabelText("Bot token"), "mm-1234567890");
    await userEvent.type(screen.getByLabelText("Server URL"), "https://mattermost.acme.internal");
    await userEvent.click(screen.getByRole("button", { name: "Register" }));

    expect(state.create.mutateAsync).toHaveBeenCalledWith({
      platform: "mattermost",
      name: "Ops bot",
      token: "mm-1234567890",
      api_base_url: "https://mattermost.acme.internal",
    });
  });

  it("will not register a Mattermost bot without its server", async () => {
    // Mattermost is self-hosted: without the address the bot cannot reply, open
    // its stream or fetch an attachment, and the backend refuses to save one.
    // Saying so here costs a round trip less than a 422.
    render(<ChannelBotsPanel canManage />);
    await pickPlatform("Mattermost");

    await userEvent.type(screen.getByLabelText("Name"), "Ops bot");
    await userEvent.type(screen.getByLabelText("Bot token"), "mm-1234567890");

    expect(screen.getByRole("button", { name: "Register" })).toBeDisabled();
  });

  it("does not send a server URL typed under Mattermost for another platform", async () => {
    render(<ChannelBotsPanel canManage />);
    await pickPlatform("Mattermost");
    await userEvent.type(screen.getByLabelText("Server URL"), "https://mattermost.acme.internal");
    await pickPlatform("Telegram");

    await userEvent.type(screen.getByLabelText("Name"), "Telegram bot");
    await userEvent.type(screen.getByLabelText("Bot token"), "1234567890123");
    await userEvent.click(screen.getByRole("button", { name: "Register" }));

    expect(state.create.mutateAsync).toHaveBeenCalledWith({
      platform: "telegram",
      name: "Telegram bot",
      token: "1234567890123",
    });
  });

  it("says when a Mattermost bot on a webhook has no token to check", async () => {
    // Mattermost does not sign bodies, so the token in the payload is the whole
    // check and a bot without one refuses every call.
    state.bots = [bot({ platform: "mattermost", webhook_mode: true, has_webhook_secret: false })];
    render(<ChannelBotsPanel canManage />);

    expect(screen.getByText("no webhook token")).toBeVisible();
  });

  it("says nothing when the token is there", async () => {
    state.bots = [bot({ platform: "mattermost", webhook_mode: true, has_webhook_secret: true })];
    render(<ChannelBotsPanel canManage />);

    expect(screen.queryByText("no webhook token")).toBeNull();
  });

  it("says nothing about a token for a bot on the event stream", async () => {
    // Nothing inbound to authenticate: the stream is an outbound socket the bot
    // token authenticates.
    state.bots = [bot({ platform: "mattermost", webhook_mode: false, has_webhook_secret: false })];
    render(<ChannelBotsPanel canManage />);

    expect(screen.queryByText("no webhook token")).toBeNull();
  });
});
