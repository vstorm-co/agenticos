import { cleanup, render, screen } from "@testing-library/react";
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

describe("the late-answer template column (#2076)", () => {
  const late = { name: "late_answer", language: "en_US", body: "Answer: {{1}} - thanks" };

  it("flags a WhatsApp bot with no late-answer template", () => {
    show(bot());

    expect(screen.getByText("No late-answer template")).toBeInTheDocument();
  });

  it("says nothing about late answers for a bot with a template or another platform", () => {
    show(bot({ whatsapp_late_template: late }));
    expect(screen.queryByText("No late-answer template")).toBeNull();

    cleanup();
    show(bot({ platform: "telegram" }));
    expect(screen.queryByText("No late-answer template")).toBeNull();
  });

  it("says nothing about a paused WhatsApp bot", () => {
    show(bot({ is_active: false }));

    expect(screen.queryByText("No late-answer template")).toBeNull();
  });
});

describe("a bot's public line badge", () => {
  it("marks a WhatsApp bot that answers people with no account", () => {
    show(
      bot({
        access_policy: { ...bot().access_policy, answer_unlinked_direct: true },
      }),
    );

    expect(screen.getByText("Public line")).toBeInTheDocument();
  });

  it("says nothing of a bot with the switch off or never set", () => {
    show(bot());
    expect(screen.queryByText("Public line")).not.toBeInTheDocument();
    cleanup();
    show(bot({ access_policy: { ...bot().access_policy, answer_unlinked_direct: false } }));
    expect(screen.queryByText("Public line")).not.toBeInTheDocument();
  });

  it("is never worn by another platform whatever its policy stored", () => {
    show(
      bot({
        platform: "slack",
        access_policy: { ...bot().access_policy, answer_unlinked_direct: true },
      }),
    );

    expect(screen.queryByText("Public line")).not.toBeInTheDocument();
  });
});
