import { render, screen, within } from "@testing-library/react";
import { NextIntlClientProvider } from "next-intl";
import { describe, expect, it, vi } from "vitest";
import messages from "../../../../messages/en.json";
import { TooltipProvider } from "@/components/ui";
import type { ChannelBot } from "@/types/channels";
import { ChannelsWidget } from "./channels";
const useBots = vi.fn();
vi.mock("@/hooks", () => ({ useChannelBots: () => useBots() }));
function bot(overrides: Partial<ChannelBot> = {}): ChannelBot {
  return {
    id: "b1",
    platform: "slack",
    name: "Jarvis",
    is_active: true,
    webhook_mode: false,
    webhook_url: null,
    api_base_url: null,
    access_policy: {
      mode: "open",
      whitelist: [],
      allowed_groups: [],
      require_link: false,
      rate_limit_rpm: 10,
      denied_message: "Denied",
    },
    has_webhook_secret: false,
    has_slack_signing_secret: false,
    has_slack_app_token: false,
    has_command_token: false,
    command_url: null,
    ack_reaction: null,
    stream_answers: true,
    step_display: "timeline",
    rate_answers: true,
    connection: null,
    transcribe_voice_notes: true,
    speech_to_text_provider: null,
    speech_to_text_model: null,
    speech_to_text_secret_id: null,
    agents: [],
    created_at: "2026-08-31T09:00:00Z",
    ...overrides,
  };
}

describe("channel connection status", () => {
  it("distinguishes down, unknown, connected, webhook and paused bots", () => {
    useBots.mockReturnValue({
      bots: [
        bot({
          id: "down",
          name: "Disconnected bot",
          connection: { state: "down", reason: "Reconnect" },
        }),
        bot({ id: "unknown", name: "Unknown bot" }),
        bot({ id: "up", name: "Connected bot", connection: { state: "up", reason: null } }),
        bot({ id: "webhook", name: "Webhook bot", webhook_mode: true }),
        bot({ id: "paused", name: "Paused bot", is_active: false }),
      ],
      isLoading: false,
      error: null,
      refetch: vi.fn(),
    });
    render(
      <NextIntlClientProvider locale="en" messages={messages}>
        <TooltipProvider>
          <ChannelsWidget title="Channels" hint="" period={{ preset: "30d", from: "", to: "" }} />
        </TooltipProvider>
      </NextIntlClientProvider>,
    );
    for (const [name, key] of [
      ["Disconnected bot", "disconnected"],
      ["Unknown bot", "unknown"],
      ["Connected bot", "polling"],
      ["Webhook bot", "webhook"],
      ["Paused bot", "switchedOff"],
    ] as const) {
      const row = screen.getByText(name).closest("li");
      expect(row).not.toBeNull();
      if (row)
        expect(within(row).getByText(messages.dashboard.widgets.channels[key])).toBeVisible();
    }
  });
});
