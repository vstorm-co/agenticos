import { useState } from "react";
import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { AnswerStyleFields, DEFAULT_ANSWER_STYLE } from "./answer-style-fields";
import { EditChannelDialog } from "./edit-channel-dialog";
import { SlackTransport } from "./slack-transport";
import type { AnswerStyle, ChannelBot, ChannelPlatform } from "@/types/channels";

vi.mock("@/hooks/use-channel-bots", () => ({
  useCopySlackManifest: () => ({ mutate: vi.fn(), isPending: false }),
}));
vi.mock("@/components/channels/transcription-fields", () => ({
  TranscriptionFields: () => null,
}));

function Harness({
  platform,
  onChange,
}: {
  platform: ChannelPlatform;
  onChange: (value: AnswerStyle) => void;
}) {
  const [value, setValue] = useState<AnswerStyle>(DEFAULT_ANSWER_STYLE);
  return (
    <AnswerStyleFields
      idPrefix="t"
      platform={platform}
      value={value}
      onChange={(next) => {
        setValue(next);
        onChange(next);
      }}
    />
  );
}

describe("how a bot answers (#2084)", () => {
  it("takes a reaction by name and turns the thumbs and the stream off", async () => {
    const onChange = vi.fn();
    render(<Harness platform="slack" onChange={onChange} />);

    await userEvent.type(screen.getByLabelText("React to a question with"), "Eyes");
    await userEvent.click(screen.getByRole("switch", { name: "Thumbs under answers" }));
    await userEvent.click(screen.getByRole("switch", { name: "Stream answers with their steps" }));

    expect(onChange).toHaveBeenLastCalledWith({
      ack_reaction: "eyes",
      stream_answers: false,
      step_display: "timeline",
      rate_answers: false,
    });
    expect(screen.getByRole("combobox", { name: "Show the steps as" })).toBeDisabled();
  });

  it("shows the steps as a plan when chosen", async () => {
    const onChange = vi.fn();
    render(<Harness platform="slack" onChange={onChange} />);

    await userEvent.click(screen.getByRole("combobox", { name: "Show the steps as" }));
    await userEvent.click(screen.getByRole("option", { name: "A plan" }));

    expect(onChange).toHaveBeenLastCalledWith(expect.objectContaining({ step_display: "plan" }));
  });

  it("says when a reaction is not an emoji's name, and clearing it means none", async () => {
    const onChange = vi.fn();
    render(<Harness platform="mattermost" onChange={onChange} />);
    const field = screen.getByLabelText("React to a question with");

    await userEvent.type(field, ":eyes:");
    expect(screen.getByText(/lower case, without colons/)).toBeInTheDocument();
    await userEvent.clear(field);

    expect(onChange).toHaveBeenLastCalledWith(expect.objectContaining({ ack_reaction: null }));
    // Streaming is Slack's alone.
    expect(screen.queryByRole("switch", { name: /Stream answers/ })).not.toBeInTheDocument();
  });

  it("lists the reactions Telegram allows", () => {
    render(<Harness platform="telegram" onChange={vi.fn()} />);
    expect(screen.getByText(/Telegram allows only some/)).toBeInTheDocument();
  });
});

describe("which way a Slack bot connects", () => {
  it("offers Slack calling us, or us connecting out", async () => {
    const onChange = vi.fn();
    render(<SlackTransport webhookMode onChange={onChange} />);

    expect(screen.getByRole("radio", { name: /Slack calls this deployment/ })).toHaveAttribute(
      "aria-checked",
      "true",
    );
    await userEvent.click(screen.getByRole("radio", { name: /AgenticOS connects to Slack/ }));
    expect(onChange).toHaveBeenCalledWith(false);
  });
});

function bot(overrides: Partial<ChannelBot>): ChannelBot {
  return {
    id: "b1",
    platform: "mattermost",
    name: "Helper",
    is_active: true,
    webhook_mode: false,
    webhook_url: null,
    api_base_url: "https://mm.acme.com",
    has_webhook_secret: false,
    has_slack_signing_secret: false,
    has_slack_app_token: false,
    has_command_token: false,
    command_url: "https://agenticos.acme.com/api/v1/mattermost/b1/commands",
    ack_reaction: null,
    stream_answers: true,
    step_display: "timeline",
    rate_answers: true,
    connection: null,
    speech_to_text_provider: null,
    speech_to_text_model: null,
    agents: [],
    created_at: "2026-10-10T09:00:00Z",
    ...overrides,
  };
}

describe("editing a bot", () => {
  it("shows a Mattermost bot where its /agent command posts, and copies it", async () => {
    const writeText = vi.fn().mockResolvedValue(undefined);
    Object.defineProperty(navigator, "clipboard", { value: { writeText }, configurable: true });
    const onSubmit = vi.fn().mockResolvedValue(undefined);
    render(
      <EditChannelDialog
        bot={bot({})}
        onOpenChange={vi.fn()}
        onSubmit={onSubmit}
        isPending={false}
      />,
    );

    await userEvent.click(screen.getByRole("button", { name: "Copy URL" }));
    expect(writeText).toHaveBeenCalledWith(
      "https://agenticos.acme.com/api/v1/mattermost/b1/commands",
    );

    await userEvent.type(screen.getByLabelText("Slash command token"), "cmd-token-1");
    await userEvent.click(screen.getByRole("button", { name: "Save" }));
    expect(onSubmit).toHaveBeenCalledWith("b1", { command_token: "cmd-token-1" });
  });

  it("asks a Slack bot that connects out for its app token, not the signing secret", async () => {
    const onSubmit = vi.fn().mockResolvedValue(undefined);
    render(
      <EditChannelDialog
        bot={bot({ platform: "slack", command_url: null, api_base_url: null })}
        onOpenChange={vi.fn()}
        onSubmit={onSubmit}
        isPending={false}
      />,
    );

    expect(screen.getByLabelText(/App-level token/)).toBeInTheDocument();
    expect(screen.queryByLabelText(/Signing secret/)).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole("radio", { name: /Slack calls this deployment/ }));
    expect(screen.getByLabelText(/Signing secret/)).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Save" }));
    expect(onSubmit).toHaveBeenCalledWith("b1", { webhook_mode: true });
  });
});
