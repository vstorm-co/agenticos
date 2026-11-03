import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { ChannelBotsTable } from "./channel-bots-table";
import type { ChannelBot } from "@/types/channels";

function bot(overrides: Partial<ChannelBot> = {}): ChannelBot {
  return {
    id: "b1",
    platform: "whatsapp",
    name: "Support line",
    is_active: true,
    webhook_mode: true,
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
    has_webhook_secret: true,
    has_slack_signing_secret: false,
    has_slack_app_token: false,
    has_command_token: false,
    command_url: null,
    whatsapp_phone_number_id: "106540352242922",
    whatsapp_account_id: "102290129340398",
    has_whatsapp_verify_token: true,
    whatsapp_callback_url: null,
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
    created_at: "2026-11-02T09:00:00Z",
    ...overrides,
  };
}

function show(row: ChannelBot) {
  render(
    <ChannelBotsTable
      bots={[row]}
      busy={false}
      onEdit={vi.fn()}
      onToggleActive={vi.fn()}
      onDelete={vi.fn()}
    />,
  );
}

describe("a bot's connection badge", () => {
  it("shows a WhatsApp bot Meta refused as unable to send, with Meta's reason", () => {
    show(bot({ connection: { state: "down", reason: "Meta refused the access token" } }));

    const badge = screen.getByText("Can't send replies");
    expect(badge).toHaveAttribute("title", "Meta refused the access token");
    expect(screen.queryByText("Not connected")).not.toBeInTheDocument();
  });

  it("still calls a polling bot with a closed socket not connected", () => {
    show(
      bot({
        platform: "telegram",
        webhook_mode: false,
        connection: { state: "down", reason: "Stream closed" },
      }),
    );

    expect(screen.getByText("Not connected")).toHaveAttribute("title", "Stream closed");
  });

  it("says nothing about a WhatsApp bot that sends fine", () => {
    show(bot({ connection: { state: "up", reason: null } }));

    expect(screen.queryByText("Can't send replies")).not.toBeInTheDocument();
    expect(screen.queryByText("Not connected")).not.toBeInTheDocument();
  });
});
