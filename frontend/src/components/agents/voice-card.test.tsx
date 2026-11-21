import { fireEvent, render as renderBase, screen } from "@testing-library/react";
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
  renderEditor(<VoiceCard value={value} onChange={onChange} />);
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
  it("shows this agent's own by default, inheriting until a provider is chosen", async () => {
    const { onChange } = mount();

    expect(screen.getByRole("radio", { name: "This agent's own" })).toHaveAttribute(
      "aria-checked",
      "true",
    );
    expect(
      screen.getByText(
        "Until you choose one, the organization's is used: OpenAI · gpt-4o-transcribe",
      ),
    ).toBeInTheDocument();
    expect(screen.getByLabelText("Provider")).toHaveTextContent("Choose a provider");
    expect(screen.queryByLabelText("Model")).not.toBeInTheDocument();
    expect(screen.getByLabelText("Language")).toHaveTextContent("Inherit (English)");
    expect(onChange).not.toHaveBeenCalled();

    await userEvent.click(screen.getByRole("radio", { name: "Organization's" }));
    expect(
      screen.getByText("From the organization: OpenAI · gpt-4o-transcribe"),
    ).toBeInTheDocument();
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
    const option = screen.getByRole("option", { name: "OpenAI (no usable key)" });
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
      screen.getByText(/the organization's is used: deepgram · gpt-4o-transcribe/),
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
    renderEditor(<VoiceCard value={null} onChange={vi.fn()} disabled />);

    expect(screen.getByRole("radio", { name: "This agent's own" })).toBeDisabled();
    expect(screen.getByLabelText("Language")).toBeDisabled();
  });

  describe("voice conversations", () => {
    const conversation = {
      value: null,
      onChange: vi.fn(),
      hasGuardrails: false,
    };

    it("shows dictation without offering unconfigured call controls or tabs", () => {
      mount();
      expect(screen.queryByRole("tablist")).not.toBeInTheDocument();
      expect(screen.queryByRole("region", { name: "Voice calls" })).not.toBeInTheDocument();
      expect(screen.getByRole("region", { name: "Dictation" })).toBeVisible();
    });
    it("lists calls and dictation together with read-only controls", () => {
      renderEditor(
        <VoiceCard value={null} onChange={vi.fn()} conversation={conversation} disabled />,
      );
      expect(screen.queryByRole("tablist")).not.toBeInTheDocument();
      const calls = screen.getByRole("region", { name: "Voice calls" });
      const dictation = screen.getByRole("region", { name: "Dictation" });
      expect(calls).toBeVisible();
      expect(dictation).toBeVisible();
      expect(
        calls.compareDocumentPosition(dictation) & Node.DOCUMENT_POSITION_FOLLOWING,
      ).toBeTruthy();
      expect(screen.getByTestId("voice-conversation-fields")).toHaveTextContent("disabled true");
      expect(screen.getByLabelText("Language")).toBeDisabled();
      expect(screen.getByRole("switch", { name: "Transcribe with a provider" })).toBeDisabled();
    });
    it("keeps transcription settings editable with dictation off for channel voice notes", async () => {
      const onChange = vi.fn();
      renderEditor(<VoiceCard value={null} onChange={onChange} conversation={conversation} />);
      expect(screen.getByRole("switch", { name: "Transcribe with a provider" })).not.toBeChecked();
      await userEvent.click(screen.getByLabelText("Language"));
      await userEvent.click(screen.getByRole("option", { name: "Polish (pl)" }));
      expect(onChange).toHaveBeenCalledWith({
        provider: null,
        model: null,
        secret_id: null,
        language: "pl",
        dictation: false,
      });
      expect(screen.getByRole("region", { name: "Voice calls" })).toBeVisible();
    });
    it("keeps Voice collapsed with a readable summary until asked", () => {
      renderBase(
        <VoiceCard collapsible value={null} onChange={vi.fn()} conversation={conversation} />,
      );
      const summary = screen.getByText("Calls off · Dictation off");
      expect(summary).toBeVisible();
      expect(summary.closest("details")).not.toHaveAttribute("open");
      expect(screen.getByText("Voice calls")).not.toBeVisible();
      expect(screen.getByText("Dictation")).not.toBeVisible();
    });
    it.each(["agent-voice", "agent-voice-dictation"])(
      "opens the matching content for #%s",
      (anchor) => {
        window.history.replaceState({}, "", `/agents/a1#${anchor}`);
        renderBase(
          <VoiceCard collapsible value={null} onChange={vi.fn()} conversation={conversation} />,
        );
        const target = document.getElementById(anchor);
        expect(target).not.toBeNull();
        expect(target?.closest("details") ?? target?.querySelector("details")).toHaveAttribute(
          "open",
        );
        expect(screen.getByRole("region", { name: "Voice calls" })).toBeVisible();
        expect(screen.getByRole("region", { name: "Dictation" })).toBeVisible();
        if (anchor === "agent-voice-dictation") {
          expect(target).toBe(screen.getByRole("region", { name: "Dictation" }));
          expect(target).toContainElement(screen.getByLabelText("Language"));
        }
        window.history.replaceState({}, "", "/");
      },
    );
  });
});

/** Existing editing cases open the same native section a person opens first. */
function renderEditor(...args: Parameters<typeof renderBase>) {
  const view = renderBase(...args);
  for (const summary of view.container.querySelectorAll<HTMLElement>(
    "details[data-focus-frame] > summary",
  )) {
    fireEvent.click(summary);
  }
  return view;
}

it("summarizes enabled calls and dictation without expanding their fields", () => {
  renderBase(
    <VoiceCard
      collapsible
      value={{ provider: null, model: null, language: null, secret_id: null, dictation: true }}
      onChange={vi.fn()}
      conversation={{
        value: {
          provider: "openai",
          model: "voice-model",
          deployment: null,
          base_model: null,
          secret_id: null,
          voice: null,
          language: null,
          max_call_seconds: null,
          voice_note: null,
        },
        onChange: vi.fn(),
        hasGuardrails: false,
      }}
    />,
  );
  expect(screen.getByText("Calls on · Dictation on")).toBeVisible();
  expect(screen.getByText("Calls on · Dictation on").closest("details")).not.toHaveAttribute(
    "open",
  );
});
