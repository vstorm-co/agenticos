import { render, screen } from "@testing-library/react";
import { NextIntlClientProvider } from "next-intl";
import { describe, expect, it, vi } from "vitest";
import messages from "../../../messages/en.json";
import { ChannelDiagnosticsDialog } from "./channel-diagnostics-dialog";
import type { ChannelBot } from "@/types/channels";
const query = vi.fn();
vi.mock("@tanstack/react-query", () => ({ useQuery: (options: unknown) => query(options) }));
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

describe("channel readiness", () => {
  it("names unconfirmed transport and personal gaps without claiming provider verification", () => {
    query.mockReturnValue({
      data: {
        checks: [
          { code: "transport", status: "unknown", detail: null },
          { code: "personal_service", status: "warning", detail: "notion" },
        ],
      },
      isLoading: false,
      error: null,
      refetch: vi.fn(),
    });
    render(
      <NextIntlClientProvider locale="en" messages={messages}>
        <ChannelDiagnosticsDialog bot={bot()} onClose={vi.fn()} />
      </NextIntlClientProvider>,
    );
    expect(screen.getByText("Unconfirmed")).toBeVisible();
    expect(screen.getByText("Needs attention")).toBeVisible();
    expect(screen.getByText("notion")).toBeVisible();
    expect(screen.getByText(messages.pages.channels.diagnostics.description)).toBeVisible();
    expect(screen.getByText(messages.pages.channels.diagnostics.audience)).toBeVisible();
  });
});
