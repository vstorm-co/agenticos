import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import {
  choiceOf,
  INHERIT,
  TranscriptionFields,
  type TranscriptionChoice,
} from "./transcription-fields";
import type { ChannelPlatform, InheritedSpeechToText } from "@/types/channels";

const state = vi.hoisted(() => ({
  providers: [] as {
    provider: string;
    name: string;
    credentialed: boolean;
    models: { id: string; name: string; description: string }[];
  }[],
}));

vi.mock("@/hooks/use-model-providers", () => ({
  useSpeechToTextProviders: () => ({ providers: state.providers, languages: [] }),
}));

const FROM_AGENT: InheritedSpeechToText = {
  provider: "openai",
  model: "gpt-4o-transcribe",
  language: "pl",
  pair_source: "agent",
  language_source: "agent",
  agent_name: "Support",
};

function mount(
  value: TranscriptionChoice = INHERIT,
  {
    platform = "slack",
    inherited = FROM_AGENT,
  }: { platform?: ChannelPlatform; inherited?: InheritedSpeechToText | null | undefined } = {},
) {
  const onChange = vi.fn();
  render(
    <TranscriptionFields
      idPrefix="t"
      value={value}
      onChange={onChange}
      platform={platform}
      inherited={inherited}
    />,
  );
  return { onChange };
}

beforeEach(() => {
  state.providers = [
    {
      provider: "openai",
      name: "OpenAI",
      credentialed: true,
      models: [
        { id: "gpt-4o-transcribe", name: "GPT-4o Transcribe", description: "Accurate." },
        { id: "whisper-1", name: "Whisper", description: "" },
      ],
    },
    {
      provider: "mistral",
      name: "Mistral",
      credentialed: true,
      models: [{ id: "voxtral-mini-latest", name: "Voxtral Mini", description: "" }],
    },
  ];
});

describe("a bot's three-way transcription choice", () => {
  it("reads a stored bot as off, its own pair, or inheriting", () => {
    expect(
      choiceOf({
        transcribe_voice_notes: false,
        speech_to_text_provider: null,
        speech_to_text_model: null,
      }).mode,
    ).toBe("off");
    expect(
      choiceOf({
        transcribe_voice_notes: true,
        speech_to_text_provider: "openai",
        speech_to_text_model: "whisper-1",
      }),
    ).toEqual({ mode: "choose", provider: "openai", model: "whisper-1" });
    expect(
      choiceOf({
        transcribe_voice_notes: true,
        speech_to_text_provider: null,
        speech_to_text_model: null,
      }),
    ).toEqual(INHERIT);
  });

  it("names what inheriting resolves to, and through which agent", () => {
    mount();

    expect(screen.getByRole("radio", { name: "Inherit" })).toHaveAttribute("aria-checked", "true");
    expect(screen.getByText("OpenAI · gpt-4o-transcribe, from agent Support")).toBeInTheDocument();
  });

  it("names the organization when that is where the pair comes from", () => {
    mount(INHERIT, { inherited: { ...FROM_AGENT, pair_source: "organization", agent_name: null } });

    expect(
      screen.getByText("OpenAI · gpt-4o-transcribe, from the organization"),
    ).toBeInTheDocument();
  });

  it("says there is nothing to inherit when nothing resolves", () => {
    mount(INHERIT, { inherited: null });

    expect(screen.getByText(/Nothing to inherit/)).toBeInTheDocument();
  });

  it("says what inheriting means while the answer is being read", () => {
    render(
      <TranscriptionFields
        idPrefix="t"
        value={INHERIT}
        onChange={vi.fn()}
        platform="slack"
        inherited={undefined}
      />,
    );

    expect(screen.getByText(/Uses the agent this bot serves/)).toBeInTheDocument();
  });

  it("choosing takes a whole pair at once", async () => {
    const { onChange } = mount();

    await userEvent.click(screen.getByRole("radio", { name: "Choose" }));

    expect(onChange).toHaveBeenCalledWith({
      mode: "choose",
      provider: "openai",
      model: "gpt-4o-transcribe",
    });
  });

  it("choosing starts on the first provider with credentials", async () => {
    state.providers[0]!.credentialed = false;
    const { onChange } = mount();

    await userEvent.click(screen.getByRole("radio", { name: "Choose" }));

    expect(onChange).toHaveBeenCalledWith({
      mode: "choose",
      provider: "mistral",
      model: "voxtral-mini-latest",
    });
  });

  it("choosing still takes a whole pair when no provider has credentials", async () => {
    state.providers.forEach((entry) => (entry.credentialed = false));
    const { onChange } = mount();

    await userEvent.click(screen.getByRole("radio", { name: "Choose" }));

    expect(onChange).toHaveBeenCalledWith({
      mode: "choose",
      provider: "openai",
      model: "gpt-4o-transcribe",
    });
  });

  it("marks a provider without credentials and keeps it unselectable, unless it is the bot's", async () => {
    state.providers[1]!.credentialed = false;
    mount({ mode: "choose", provider: "openai", model: "gpt-4o-transcribe" });

    await userEvent.click(screen.getByLabelText("Provider"));

    expect(screen.getByRole("option", { name: "Mistral (no credentials)" })).toHaveAttribute(
      "aria-disabled",
      "true",
    );
    expect(screen.getByRole("option", { name: "OpenAI" })).not.toHaveAttribute("aria-disabled");
  });

  it("keeps a stored provider that lost its credentials selectable", async () => {
    state.providers[0]!.credentialed = false;
    mount({ mode: "choose", provider: "openai", model: "gpt-4o-transcribe" });

    await userEvent.click(screen.getByLabelText("Provider"));

    expect(screen.getByRole("option", { name: "OpenAI (no credentials)" })).not.toHaveAttribute(
      "aria-disabled",
    );
  });

  it("off and inherit both clear the pair", async () => {
    const { onChange } = mount({ mode: "choose", provider: "openai", model: "gpt-4o-transcribe" });

    await userEvent.click(screen.getByRole("radio", { name: "Off" }));
    await userEvent.click(screen.getByRole("radio", { name: "Inherit" }));

    expect(onChange).toHaveBeenNthCalledWith(1, { mode: "off", provider: null, model: null });
    expect(onChange).toHaveBeenNthCalledWith(2, INHERIT);
  });

  it("says what off means", () => {
    mount({ mode: "off", provider: null, model: null });

    expect(screen.getByText(/are not transcribed; the sender is told/)).toBeInTheDocument();
  });

  it("switching provider takes its first model, and the model can change alone", async () => {
    const { onChange } = mount({ mode: "choose", provider: "openai", model: "gpt-4o-transcribe" });

    expect(screen.getByText("Accurate.")).toBeInTheDocument();
    await userEvent.click(screen.getByLabelText("Provider"));
    await userEvent.click(screen.getByRole("option", { name: "Mistral" }));
    await userEvent.click(screen.getByLabelText("Transcription model"));
    await userEvent.click(screen.getByRole("option", { name: "Whisper" }));

    expect(onChange).toHaveBeenNthCalledWith(1, {
      mode: "choose",
      provider: "mistral",
      model: "voxtral-mini-latest",
    });
    expect(onChange).toHaveBeenNthCalledWith(2, {
      mode: "choose",
      provider: "openai",
      model: "whisper-1",
    });
  });

  it("warns a Telegram bot inheriting Mistral that its Ogg notes may fail", () => {
    mount(INHERIT, {
      platform: "telegram",
      inherited: { ...FROM_AGENT, provider: "mistral", model: "voxtral-mini-latest" },
    });

    expect(screen.getByRole("note")).toHaveTextContent(/Ogg\/Opus/);
  });

  it("warns a Telegram bot choosing Mistral", () => {
    mount(
      { mode: "choose", provider: "mistral", model: "voxtral-mini-latest" },
      { platform: "telegram" },
    );
    expect(screen.getByRole("note")).toBeInTheDocument();
  });

  it("warns a Slack bot on Mistral that its WebM clips may fail", () => {
    mount({ mode: "choose", provider: "mistral", model: "voxtral-mini-latest" });

    expect(screen.getByRole("note")).toHaveTextContent(/WebM/);
  });

  it("does not warn a Mattermost bot on Mistral, or a Telegram bot switched off", () => {
    const { unmount } = render(
      <TranscriptionFields
        idPrefix="a"
        value={{ mode: "choose", provider: "mistral", model: "voxtral-mini-latest" }}
        onChange={vi.fn()}
        platform="mattermost"
        inherited={null}
      />,
    );
    expect(screen.queryByRole("note")).not.toBeInTheDocument();
    unmount();

    mount({ mode: "off", provider: null, model: null }, { platform: "telegram" });
    expect(screen.queryByRole("note")).not.toBeInTheDocument();
  });

  it("renders nothing while the deployment offers no provider", () => {
    state.providers = [];
    const { container } = render(
      <TranscriptionFields
        idPrefix="t"
        value={INHERIT}
        onChange={vi.fn()}
        platform="slack"
        inherited={null}
      />,
    );

    expect(container).toBeEmptyDOMElement();
  });
});
