import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { VoiceCard } from "./voice-card";
import type { SpeechToTextSpec } from "@/types/agents";

interface Org {
  id: string;
  speech_to_text_provider: string | null;
  speech_to_text_model: string | null;
  speech_to_text_language: string | null;
}

const state = vi.hoisted(() => ({
  org: null as Org | null,
  providers: [] as {
    provider: string;
    name: string;
    models: { id: string; name: string; description: string }[];
  }[],
  /** Providers with a key this person can choose. */
  keyed: new Set<string>(),
  keyField: [] as { provider: string; value: string | null; orgVisibleOnly: boolean }[],
}));

vi.mock("@/hooks", () => ({
  useOrganizationList: () => ({ data: state.org ? [state.org] : [] }),
}));
vi.mock("@/hooks/use-model-providers", () => ({
  useSpeechToTextProviders: () => ({ providers: state.providers, languages: ["en", "pl", "de"] }),
}));
vi.mock("@/components/vault/speech-key-field", () => ({
  useSpeechKeyCheck: () => (provider: string) => state.keyed.has(provider),
  SpeechKeyField: (props: {
    provider: string;
    value: string | null;
    orgVisibleOnly: boolean;
    onChange: (id: string) => void;
  }) => {
    state.keyField.push(props);
    return (
      <button type="button" onClick={() => props.onChange(`key-${props.provider}`)}>
        choose key
      </button>
    );
  },
}));
vi.mock("./voice-conversation-fields", () => ({
  VoiceConversationFields: (props: { disabled?: boolean }) => (
    <p data-testid="voice-conversation-fields">{`disabled ${String(props.disabled)}`}</p>
  ),
}));
vi.mock("@/stores", () => ({
  useOrgStore: (select: (s: { activeOrgId: string }) => unknown) =>
    select({ activeOrgId: "org-1" }),
}));

function model(id: string) {
  return { id, name: id, description: "" };
}

function mount(value: SpeechToTextSpec | null = null) {
  const onChange = vi.fn();
  render(<VoiceCard value={value} onChange={onChange} />);
  return { onChange };
}

beforeEach(() => {
  state.org = {
    id: "org-1",
    speech_to_text_provider: "openai",
    speech_to_text_model: "gpt-4o-transcribe",
    speech_to_text_language: "en",
  };
  state.providers = [
    { provider: "openai", name: "OpenAI", models: [model("whisper-1")] },
    {
      provider: "groq",
      name: "Groq",
      models: [model("whisper-large-v3"), model("whisper-large-v3-turbo")],
    },
  ];
  state.keyed = new Set(["groq"]);
  state.keyField = [];
});

function pair(provider: string, modelId: string, language: string | null = null) {
  return { provider, model: modelId, language, secret_id: `key-${provider}`, dictation: false };
}

describe("the agent's Voice card", () => {
  it("inherits by default and names what it inherits", () => {
    mount();

    expect(screen.getByRole("radio", { name: "Organization's" })).toHaveAttribute(
      "aria-checked",
      "true",
    );
    expect(
      screen.getByText("From the organization: OpenAI · gpt-4o-transcribe"),
    ).toBeInTheDocument();
    expect(screen.getByLabelText("Language")).toHaveTextContent("Inherit (English)");
    expect(screen.queryByLabelText("Provider")).not.toBeInTheDocument();
  });

  it("chooses a whole pair at once, on a provider with a key, and no key yet", async () => {
    const { onChange } = mount();

    await userEvent.click(screen.getByRole("radio", { name: "This agent's own" }));

    // In the spec's order, with explicit nulls, so the draft compares equal to
    // what the server stores.
    expect(onChange).toHaveBeenCalledWith({
      provider: "groq",
      model: "whisper-large-v3",
      language: null,
      secret_id: null,
      dictation: false,
    });
    expect(Object.keys(onChange.mock.calls[0]![0])).toEqual([
      "provider",
      "model",
      "language",
      "secret_id",
      "dictation",
    ]);
  });

  it("offers any key this person can see for the chosen provider", async () => {
    const { onChange } = mount({ ...pair("groq", "whisper-large-v3"), secret_id: null });

    expect(state.keyField.at(-1)).toMatchObject({
      provider: "groq",
      value: null,
      orgVisibleOnly: false,
    });
    await userEvent.click(screen.getByRole("button", { name: "choose key" }));

    expect(onChange).toHaveBeenCalledWith(pair("groq", "whisper-large-v3"));
  });

  it("marks a provider without a key, and still lets it be chosen to add one", async () => {
    const { onChange } = mount(pair("groq", "whisper-large-v3"));

    await userEvent.click(screen.getByLabelText("Provider"));
    const option = screen.getByRole("option", { name: "OpenAI (no key yet)" });
    expect(option).not.toHaveAttribute("aria-disabled");
    await userEvent.click(option);

    expect(onChange).toHaveBeenCalledWith({
      provider: "openai",
      model: "whisper-1",
      language: null,
      secret_id: null,
      dictation: false,
    });
  });

  it("switching provider takes that provider's first model and drops the old key", async () => {
    state.keyed.add("openai");
    const { onChange } = mount(pair("groq", "whisper-large-v3", "pl"));

    await userEvent.click(screen.getByLabelText("Provider"));
    await userEvent.click(screen.getByRole("option", { name: "OpenAI" }));

    expect(onChange).toHaveBeenCalledWith({
      provider: "openai",
      model: "whisper-1",
      language: "pl",
      secret_id: null,
      dictation: false,
    });
  });

  it("changes the model alone, keeping the key", async () => {
    const { onChange } = mount(pair("groq", "whisper-large-v3"));

    await userEvent.click(screen.getByLabelText("Model"));
    await userEvent.click(screen.getByRole("option", { name: "whisper-large-v3-turbo" }));

    expect(onChange).toHaveBeenCalledWith(pair("groq", "whisper-large-v3-turbo"));
  });

  it("pins a language on its own, keeping the organization's provider", async () => {
    const { onChange } = mount();

    await userEvent.click(screen.getByLabelText("Language"));
    await userEvent.click(screen.getByRole("option", { name: "Polish (pl)" }));

    expect(onChange).toHaveBeenCalledWith({
      provider: null,
      model: null,
      language: "pl",
      secret_id: null,
      dictation: false,
    });
  });

  it("returns to inherit as no block at all, key and all", async () => {
    const { onChange } = mount(pair("groq", "whisper-large-v3"));

    await userEvent.click(screen.getByRole("radio", { name: "Organization's" }));

    expect(onChange).toHaveBeenCalledWith(null);
  });

  it("keeps a pinned language when the pair goes back to inherit", async () => {
    const { onChange } = mount(pair("groq", "whisper-large-v3", "pl"));

    await userEvent.click(screen.getByRole("radio", { name: "Organization's" }));

    expect(onChange).toHaveBeenCalledWith({
      provider: null,
      model: null,
      language: "pl",
      secret_id: null,
      dictation: false,
    });
  });

  it("inheriting the language back clears the block", async () => {
    const { onChange } = mount({
      provider: null,
      model: null,
      language: "pl",
      secret_id: null,
      dictation: false,
    });

    await userEvent.click(screen.getByLabelText("Language"));
    await userEvent.click(screen.getByRole("option", { name: "Inherit (English)" }));

    expect(onChange).toHaveBeenCalledWith(null);
  });

  it("says inheriting from an organization with no language is auto-detect", () => {
    state.org!.speech_to_text_language = null;
    mount();

    expect(screen.getByLabelText("Language")).toHaveTextContent("Inherit (auto-detect)");
  });

  it("says the provider reaches only channel bots while the Dictation switch is off", () => {
    mount();

    expect(screen.getByRole("switch", { name: "Transcribe with a provider" })).not.toBeChecked();
    expect(screen.getByText(/only changes how voice notes/)).toBeInTheDocument();
  });

  it("switches provider dictation on, written as a block of its own", async () => {
    const { onChange } = mount();

    await userEvent.click(screen.getByRole("switch", { name: "Transcribe with a provider" }));

    expect(onChange).toHaveBeenCalledWith({
      provider: null,
      model: null,
      language: null,
      secret_id: null,
      dictation: true,
    });
  });

  it("writes a block with only the switch back as nothing when it goes off", async () => {
    const { onChange } = mount({
      provider: null,
      model: null,
      language: null,
      secret_id: null,
      dictation: true,
    });

    await userEvent.click(screen.getByRole("switch", { name: "Transcribe with a provider" }));

    expect(onChange).toHaveBeenCalledWith(null);
  });

  it("says the browser keeps transcribing when the switch is on and nothing resolves", () => {
    state.org!.speech_to_text_provider = null;
    state.org!.speech_to_text_model = null;
    mount({ provider: null, model: null, language: null, secret_id: null, dictation: true });

    expect(screen.getByText(/the browser keeps transcribing/)).toBeInTheDocument();
    expect(screen.getByText(/nothing to inherit/)).toBeInTheDocument();
  });

  it("says nothing more once this agent's own provider is chosen", () => {
    state.org!.speech_to_text_provider = null;
    state.org!.speech_to_text_model = null;
    mount({ ...pair("groq", "whisper-large-v3"), dictation: true });

    expect(screen.queryByText(/the browser keeps transcribing/)).not.toBeInTheDocument();
  });

  it("chooses the first offered provider when none has a key", async () => {
    state.keyed.clear();
    const { onChange } = mount();

    await userEvent.click(screen.getByRole("radio", { name: "This agent's own" }));

    expect(onChange).toHaveBeenCalledWith({
      provider: "openai",
      model: "whisper-1",
      language: null,
      secret_id: null,
      dictation: false,
    });
  });

  it("shows a half-made pair from a draft as a choice still to finish", () => {
    mount({
      provider: null,
      model: "whisper-1",
      language: null,
      secret_id: null,
      dictation: false,
    });
    expect(screen.getByRole("radio", { name: "This agent's own" })).toHaveAttribute(
      "aria-checked",
      "true",
    );
    expect(screen.queryByRole("button", { name: "choose key" })).not.toBeInTheDocument();
  });

  it("offers the key once a provider is chosen, before its model is", () => {
    mount({ provider: "groq", model: null, language: null, secret_id: null, dictation: false });
    expect(screen.getByRole("button", { name: "choose key" })).toBeInTheDocument();
  });

  it("names an organization provider the catalog no longer lists by its id", () => {
    state.org!.speech_to_text_provider = "deepgram";
    mount();
    expect(
      screen.getByText("From the organization: deepgram · gpt-4o-transcribe"),
    ).toBeInTheDocument();
  });

  it("asks for no key for a provider the catalog no longer offers", () => {
    mount(pair("deepgram", "nova"));

    expect(screen.queryByRole("button", { name: "choose key" })).not.toBeInTheDocument();
  });

  it("cannot choose anything while the catalog offers nothing", () => {
    state.providers = [];
    state.org = null;
    mount();

    expect(screen.getByRole("radio", { name: "This agent's own" })).toBeDisabled();
    expect(screen.queryByText(/so this only changes/)).not.toBeInTheDocument();
  });

  it("is read-only for a caller who may not edit the agent", () => {
    render(<VoiceCard value={null} onChange={vi.fn()} disabled />);

    expect(screen.getByRole("radio", { name: "This agent's own" })).toBeDisabled();
    expect(screen.getByLabelText("Language")).toBeDisabled();
  });

  describe("voice conversations", () => {
    const conversation = {
      value: null,
      onChange: vi.fn(),
      capabilityIds: [],
      hasGuardrails: false,
    };

    it("are not offered where the page does not ask for them", () => {
      mount();
      expect(screen.queryByRole("tab", { name: "Voice calls" })).toBeNull();
      expect(screen.getByRole("tab", { name: "Dictation" })).toHaveAttribute(
        "aria-selected",
        "true",
      );
    });

    it("open on their own tab, apart from dictation", async () => {
      render(<VoiceCard value={null} onChange={vi.fn()} conversation={conversation} disabled />);
      expect(screen.getByRole("tab", { name: "Voice calls" })).toHaveAttribute(
        "aria-selected",
        "true",
      );
      expect(screen.getByTestId("voice-conversation-fields")).toHaveTextContent("disabled true");
      // Dictation's settings are on the other tab, not stacked beneath.
      expect(screen.queryByLabelText("Language")).toBeNull();
      await userEvent.click(screen.getByRole("tab", { name: "Dictation" }));
      expect(screen.getByLabelText("Language")).toBeInTheDocument();
    });

    it("give way to the Dictation tab for a link to the dictation setup", () => {
      window.history.replaceState({}, "", "/agents/a1#agent-voice-dictation");
      render(<VoiceCard value={null} onChange={vi.fn()} conversation={conversation} />);
      expect(screen.getByRole("tab", { name: "Dictation" })).toHaveAttribute(
        "aria-selected",
        "true",
      );
      window.history.replaceState({}, "", "/");
    });
  });
});
