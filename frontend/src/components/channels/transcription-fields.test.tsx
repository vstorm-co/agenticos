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
    models: { id: string; name: string; description: string }[];
  }[],
  /** Providers with an organization-wide key. */
  keyed: new Set<string>(),
  keyField: [] as { provider: string; value: string | null; orgVisibleOnly: boolean }[],
}));

vi.mock("@/hooks/use-model-providers", () => ({
  useSpeechToTextProviders: () => ({ providers: state.providers, languages: [] }),
}));
vi.mock("@/components/vault/speech-key-field", () => ({
  useSpeechKeyCheck: () => (provider: string) => state.keyed.has(provider),
  SpeechKeyField: (props: {
    provider: string;
    value: string | null;
    orgVisibleOnly: boolean;
    error?: string;
    onChange: (id: string) => void;
  }) => {
    state.keyField.push(props);
    return (
      <>
        <button type="button" onClick={() => props.onChange(`key-${props.provider}`)}>
          choose key
        </button>
        {props.error && <p>{props.error}</p>}
      </>
    );
  },
}));

function choose(provider: string, model: string, secretId: string | null = `key-${provider}`) {
  return { mode: "choose" as const, provider, model, secretId };
}

const FROM_AGENT: InheritedSpeechToText = {
  provider: "openai",
  model: "gpt-4o-transcribe",
  language: "pl",
  pair_source: "agent",
  language_source: "agent",
  agent_name: "Support",
  has_key: true,
};

function mount(
  value: TranscriptionChoice = INHERIT,
  {
    platform = "slack",
    inherited = FROM_AGENT,
    keyError,
  }: {
    platform?: ChannelPlatform;
    inherited?: InheritedSpeechToText | null | undefined;
    keyError?: string;
  } = {},
) {
  const onChange = vi.fn();
  render(
    <TranscriptionFields
      idPrefix="t"
      value={value}
      onChange={onChange}
      platform={platform}
      inherited={inherited}
      keyError={keyError}
    />,
  );
  return { onChange };
}

beforeEach(() => {
  state.providers = [
    {
      provider: "openai",
      name: "OpenAI",
      models: [
        { id: "gpt-4o-transcribe", name: "GPT-4o Transcribe", description: "Accurate." },
        { id: "whisper-1", name: "Whisper", description: "" },
      ],
    },
    {
      provider: "mistral",
      name: "Mistral",
      models: [{ id: "voxtral-mini-latest", name: "Voxtral Mini", description: "" }],
    },
  ];
  state.keyed = new Set(["openai", "mistral"]);
  state.keyField = [];
});

describe("a bot's three-way transcription choice", () => {
  it("reads a stored bot as off, its own pair, or inheriting", () => {
    expect(
      choiceOf({
        transcribe_voice_notes: false,
        speech_to_text_provider: null,
        speech_to_text_model: null,
        speech_to_text_secret_id: null,
      }).mode,
    ).toBe("off");
    expect(
      choiceOf({
        transcribe_voice_notes: true,
        speech_to_text_provider: "openai",
        speech_to_text_model: "whisper-1",
        speech_to_text_secret_id: "key-openai",
      }),
    ).toEqual(choose("openai", "whisper-1"));
    expect(
      choiceOf({
        transcribe_voice_notes: true,
        speech_to_text_provider: null,
        speech_to_text_model: null,
        speech_to_text_secret_id: null,
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

  it("warns that an inherited pair with no key transcribes nothing", () => {
    mount(INHERIT, { inherited: { ...FROM_AGENT, has_key: false } });

    expect(screen.getByRole("note")).toHaveTextContent(
      /No key is chosen where this pair comes from/,
    );
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

  it("choosing takes a whole pair at once, with its key still to choose", async () => {
    const { onChange } = mount();

    await userEvent.click(screen.getByRole("radio", { name: "Choose" }));

    expect(onChange).toHaveBeenCalledWith(choose("openai", "gpt-4o-transcribe", null));
  });

  it("choosing starts on the first provider with an organization-wide key", async () => {
    state.keyed.delete("openai");
    const { onChange } = mount();

    await userEvent.click(screen.getByRole("radio", { name: "Choose" }));

    expect(onChange).toHaveBeenCalledWith(choose("mistral", "voxtral-mini-latest", null));
  });

  it("choosing still takes a whole pair when no provider has a key", async () => {
    state.keyed.clear();
    const { onChange } = mount();

    await userEvent.click(screen.getByRole("radio", { name: "Choose" }));

    expect(onChange).toHaveBeenCalledWith(choose("openai", "gpt-4o-transcribe", null));
  });

  it("offers only organization-wide keys for the bot's own pair", async () => {
    const { onChange } = mount(choose("openai", "gpt-4o-transcribe", null), {
      keyError: "Choose a key for openai to transcribe with",
    });

    expect(state.keyField.at(-1)).toMatchObject({
      provider: "openai",
      value: null,
      orgVisibleOnly: true,
    });
    expect(screen.getByText("Choose a key for openai to transcribe with")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "choose key" }));

    expect(onChange).toHaveBeenCalledWith(choose("openai", "gpt-4o-transcribe"));
  });

  it("marks a provider without a key and still lets it be chosen", async () => {
    state.keyed.delete("mistral");
    mount(choose("openai", "gpt-4o-transcribe"));

    await userEvent.click(screen.getByLabelText("Provider"));

    expect(screen.getByRole("option", { name: "Mistral (no usable key)" })).not.toHaveAttribute(
      "aria-disabled",
    );
    expect(screen.getByRole("option", { name: "OpenAI" })).toBeInTheDocument();
  });

  it("off and inherit both clear the pair and its key", async () => {
    const { onChange } = mount(choose("openai", "gpt-4o-transcribe"));

    await userEvent.click(screen.getByRole("radio", { name: "Off" }));
    await userEvent.click(screen.getByRole("radio", { name: "Inherit" }));

    expect(onChange).toHaveBeenNthCalledWith(1, { ...INHERIT, mode: "off" });
    expect(onChange).toHaveBeenNthCalledWith(2, INHERIT);
  });

  it("says what off means", () => {
    mount({ ...INHERIT, mode: "off" });

    expect(screen.getByText(/are not transcribed; the sender is told/)).toBeInTheDocument();
  });

  it("switching provider takes its first model and drops the key; the model changes alone", async () => {
    const { onChange } = mount(choose("openai", "gpt-4o-transcribe"));

    expect(screen.getByText("Accurate.")).toBeInTheDocument();
    await userEvent.click(screen.getByLabelText("Provider"));
    await userEvent.click(screen.getByRole("option", { name: "Mistral" }));
    await userEvent.click(screen.getByLabelText("Transcription model"));
    await userEvent.click(screen.getByRole("option", { name: "Whisper" }));

    expect(onChange).toHaveBeenNthCalledWith(1, choose("mistral", "voxtral-mini-latest", null));
    expect(onChange).toHaveBeenNthCalledWith(2, choose("openai", "whisper-1"));
  });

  it("warns a Telegram bot inheriting Mistral that its Ogg notes may fail", () => {
    mount(INHERIT, {
      platform: "telegram",
      inherited: { ...FROM_AGENT, provider: "mistral", model: "voxtral-mini-latest" },
    });

    expect(screen.getByRole("note")).toHaveTextContent(/Ogg\/Opus/);
  });

  it("warns a Telegram bot choosing Mistral", () => {
    mount(choose("mistral", "voxtral-mini-latest"), { platform: "telegram" });
    expect(screen.getByRole("note")).toBeInTheDocument();
  });

  it("names Discord, not Telegram, when warning a Discord bot on Mistral", () => {
    mount(choose("mistral", "voxtral-mini-latest"), { platform: "discord" });

    expect(screen.getByRole("note")).toHaveTextContent(
      /^Discord sends voice messages as Ogg\/Opus/,
    );
  });

  it("warns a Slack bot on Mistral that its WebM clips may fail", () => {
    mount(choose("mistral", "voxtral-mini-latest"));

    expect(screen.getByRole("note")).toHaveTextContent(/WebM/);
  });

  it("does not warn a Mattermost bot on Mistral, or a Telegram bot switched off", () => {
    const { unmount } = render(
      <TranscriptionFields
        idPrefix="a"
        value={choose("mistral", "voxtral-mini-latest")}
        onChange={vi.fn()}
        platform="mattermost"
        inherited={null}
      />,
    );
    expect(screen.queryByRole("note")).not.toBeInTheDocument();
    unmount();

    mount({ ...INHERIT, mode: "off" }, { platform: "telegram" });
    expect(screen.queryByRole("note")).not.toBeInTheDocument();
  });

  it("copes with a stored provider the catalog no longer offers", () => {
    mount(
      { mode: "choose", provider: "deepgram", model: null, secretId: null },
      { inherited: { ...FROM_AGENT, provider: "deepgram" } },
    );

    expect(screen.getByText("Which of that provider's models to use.")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "choose key" })).not.toBeInTheDocument();
  });

  it("shows Choose with nothing picked yet as an empty pair", () => {
    mount({ mode: "choose", provider: null, model: null, secretId: null });

    expect(screen.getByLabelText("Provider")).toBeInTheDocument();
  });

  it("names an inherited provider the catalog no longer offers by its id", () => {
    mount(INHERIT, { inherited: { ...FROM_AGENT, provider: "deepgram" } });

    expect(
      screen.getByText("deepgram · gpt-4o-transcribe, from agent Support"),
    ).toBeInTheDocument();
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
