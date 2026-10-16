import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { VoiceSpec } from "@/types/agents";
import type { RealtimeProvider } from "@/types/voice";

import { VoiceConversationFields, type VoiceConversationProps } from "./voice-conversation-fields";

const PROVIDERS: RealtimeProvider[] = [
  {
    provider: "openai",
    name: "OpenAI",
    secret_kind: "api_key",
    deployment: false,
    models: [
      {
        id: "gpt-realtime",
        name: "GPT Realtime",
        description: "",
        transport: "webrtc",
        voices: ["marin", "cedar"],
        default_voice: "marin",
        supports_thinking: false,
        input_sample_rate: 24000,
        output_sample_rate: 24000,
      },
      {
        id: "gpt-realtime-mini",
        name: "GPT Realtime mini",
        description: "",
        transport: "webrtc",
        voices: ["cedar", "ash"],
        default_voice: "ash",
        supports_thinking: false,
        input_sample_rate: 24000,
        output_sample_rate: 24000,
      },
    ],
  },
  {
    provider: "azure",
    name: "Azure OpenAI",
    secret_kind: "azure_openai",
    deployment: true,
    models: [
      {
        id: "gpt-realtime",
        name: "GPT Realtime (Azure deployment)",
        description: "",
        transport: "relay",
        voices: ["marin"],
        default_voice: "marin",
        supports_thinking: false,
        input_sample_rate: 24000,
        output_sample_rate: 24000,
      },
      {
        id: "gpt-realtime-mini",
        name: "GPT Realtime mini (Azure deployment)",
        description: "",
        transport: "relay",
        voices: ["ash"],
        default_voice: "ash",
        supports_thinking: false,
        input_sample_rate: 24000,
        output_sample_rate: 24000,
      },
    ],
  },
];

const state = vi.hoisted(() => ({ providers: [] as unknown[], isError: false }));

vi.mock("@/hooks/use-realtime-models", () => ({
  useRealtimeModels: () => ({
    providers: state.providers,
    isLoading: false,
    isError: state.isError,
  }),
}));
vi.mock("@/hooks/use-agents", () => ({
  useCapabilityCatalog: () => ({
    capabilities: [
      { id: "sandbox", name: "Sandbox", voice: false },
      { id: "knowledge", name: "Knowledge", voice: true },
    ],
    isLoading: false,
  }),
}));
vi.mock("@/hooks/use-model-providers", () => ({
  useSpeechToTextProviders: () => ({ providers: [], languages: ["en", "pl"] }),
}));
vi.mock("@/components/vault/speech-key-field", () => ({
  SpeechKeyField: (props: {
    kind: string;
    provider: string;
    suggestedName: string;
    onChange: (id: string) => void;
  }) => (
    <button
      type="button"
      data-testid="speech-key-field"
      data-kind={props.kind}
      onClick={() => props.onChange(`key-${props.provider}`)}
    >
      {props.suggestedName}
    </button>
  ),
}));

const EMPTY: VoiceSpec = {
  provider: null,
  model: null,
  deployment: null,
  base_model: null,
  secret_id: null,
  voice: null,
  language: null,
  max_call_seconds: null,
  voice_note: null,
};
const OPENAI: VoiceSpec = { ...EMPTY, provider: "openai", model: "gpt-realtime", voice: "marin" };

function mount(props: Partial<VoiceConversationProps> = {}) {
  const onChange = vi.fn();
  const view = render(
    <VoiceConversationFields
      value={OPENAI}
      onChange={onChange}
      capabilityIds={[]}
      hasGuardrails={false}
      orgMaxSeconds={600}
      {...props}
    />,
  );
  return { onChange, view };
}

async function choose(label: string, option: string) {
  await userEvent.click(screen.getByLabelText(label));
  await userEvent.click(await screen.findByRole("option", { name: option }));
}

beforeEach(() => {
  state.providers = PROVIDERS;
  state.isError = false;
});

describe("VoiceConversationFields", () => {
  it("turning calls on picks the first provider's first model and its default voice", async () => {
    const { onChange } = mount({ value: null });
    expect(screen.queryByLabelText("Call provider")).toBeNull();
    await userEvent.click(screen.getByRole("switch", { name: "Take voice calls" }));
    expect(onChange).toHaveBeenCalledWith({ ...OPENAI });
    // Every key, in the spec's order, so the draft compares equal to what is stored.
    expect(Object.keys(onChange.mock.calls[0]![0])).toEqual(Object.keys(EMPTY));
  });

  it("cannot be turned on before the catalog has anything to offer", () => {
    state.providers = [];
    mount({ value: undefined });
    expect(screen.getByRole("switch", { name: "Take voice calls" })).toBeDisabled();
  });

  it("says why calls cannot be turned on when the catalog could not be read", () => {
    state.providers = [];
    state.isError = true;
    mount({ value: null });
    expect(screen.getByRole("switch", { name: "Take voice calls" })).toBeDisabled();
    expect(screen.getByRole("alert")).toHaveTextContent("could not be loaded");
  });

  it("turning calls off writes null", async () => {
    const { onChange } = mount();
    await userEvent.click(screen.getByRole("switch", { name: "Take voice calls" }));
    expect(onChange).toHaveBeenCalledWith(null);
  });

  it("asks Azure for a deployment name and a base model, and a key of the Azure kind", async () => {
    const { onChange } = mount({
      value: { ...EMPTY, provider: "azure", base_model: "gpt-realtime" },
    });
    expect(screen.getByLabelText("Deployment name")).toBeInTheDocument();
    expect(screen.getByLabelText("Base model")).toHaveTextContent(
      "GPT Realtime (Azure deployment)",
    );
    expect(screen.queryByLabelText("Call model")).toBeNull();
    expect(screen.getByTestId("speech-key-field")).toHaveAttribute("data-kind", "azure_openai");

    await userEvent.type(screen.getByLabelText("Deployment name"), "r");
    expect(onChange).toHaveBeenLastCalledWith({
      ...EMPTY,
      provider: "azure",
      base_model: "gpt-realtime",
      deployment: "r",
    });
  });

  it("clears a deployment name emptied out", async () => {
    const { onChange } = mount({
      value: { ...EMPTY, provider: "azure", base_model: "gpt-realtime", deployment: "x" },
    });
    await userEvent.clear(screen.getByLabelText("Deployment name"));
    expect(onChange).toHaveBeenLastCalledWith({
      ...EMPTY,
      provider: "azure",
      base_model: "gpt-realtime",
    });
  });

  it("switching to Azure takes its first model as the base and drops the key", async () => {
    const { onChange } = mount({ value: { ...OPENAI, secret_id: "key-openai" } });
    await choose("Call provider", "Azure OpenAI");
    expect(onChange).toHaveBeenCalledWith({
      ...EMPTY,
      provider: "azure",
      base_model: "gpt-realtime",
      voice: "marin",
    });
  });

  it("switching back from Azure takes the first model", async () => {
    const { onChange } = mount({
      value: { ...EMPTY, provider: "azure", base_model: "gpt-realtime", deployment: "d" },
    });
    await choose("Call provider", "OpenAI");
    expect(onChange).toHaveBeenCalledWith({ ...OPENAI });
  });

  it("changes the model, and its voice when the old one is not among the new model's", async () => {
    const { onChange } = mount({ value: { ...OPENAI, voice: "marin" } });
    await choose("Call model", "GPT Realtime mini");
    expect(onChange).toHaveBeenCalledWith({ ...OPENAI, model: "gpt-realtime-mini", voice: "ash" });
  });

  it("keeps a voice the new model also has", async () => {
    const { onChange } = mount({ value: { ...OPENAI, voice: "cedar" } });
    await choose("Call model", "GPT Realtime mini");
    expect(onChange).toHaveBeenCalledWith({
      ...OPENAI,
      model: "gpt-realtime-mini",
      voice: "cedar",
    });
  });

  it("changes the base model of a deployment", async () => {
    const { onChange } = mount({
      value: { ...EMPTY, provider: "azure", base_model: "gpt-realtime" },
    });
    await choose("Base model", "GPT Realtime mini (Azure deployment)");
    expect(onChange).toHaveBeenCalledWith({
      ...EMPTY,
      provider: "azure",
      base_model: "gpt-realtime-mini",
      voice: "ash",
    });
  });

  it("chooses a voice, marking the model's default", async () => {
    const { onChange } = mount({ value: { ...OPENAI, voice: null } });
    expect(screen.getByLabelText("Voice")).toHaveTextContent("marin (default)");
    await choose("Voice", "cedar");
    expect(onChange).toHaveBeenCalledWith({ ...OPENAI, voice: "cedar" });
  });

  it("names the key a voice key, and stores the one chosen", async () => {
    const { onChange } = mount();
    const field = screen.getByTestId("speech-key-field");
    expect(field).toHaveAttribute("data-kind", "api_key");
    expect(field).toHaveTextContent("OpenAI voice calls");
    await userEvent.click(field);
    expect(onChange).toHaveBeenCalledWith({ ...OPENAI, secret_id: "key-openai" });
  });

  it("pins a language, or follows the caller", async () => {
    const { onChange, view } = mount();
    expect(screen.getByLabelText("Spoken language")).toHaveTextContent("Follow the caller");
    await choose("Spoken language", "Polish (pl)");
    expect(onChange).toHaveBeenCalledWith({ ...OPENAI, language: "pl" });

    view.rerender(
      <VoiceConversationFields
        value={{ ...OPENAI, language: "pl" }}
        onChange={onChange}
        capabilityIds={[]}
        hasGuardrails={false}
        orgMaxSeconds={600}
      />,
    );
    await choose("Spoken language", "Follow the caller");
    expect(onChange).toHaveBeenLastCalledWith({ ...OPENAI });
  });

  it("lists the capabilities a call cannot use", () => {
    mount({ capabilityIds: ["sandbox", "knowledge", "unknown"] });
    expect(screen.getByText("Not available in calls")).toBeInTheDocument();
    expect(screen.getByText("Sandbox")).toBeInTheDocument();
    expect(screen.queryByText("Knowledge")).toBeNull();
  });

  it("lists nothing when every capability can run in a call", () => {
    mount({ capabilityIds: ["knowledge"] });
    expect(screen.queryByText("Not available in calls")).toBeNull();
  });

  it("says plainly that guardrails cannot filter speech before it is heard", () => {
    mount({ hasGuardrails: true });
    expect(screen.getByText(/cannot be filtered before they are heard/)).toBeInTheDocument();
  });

  it("says no audio is kept", () => {
    mount();
    expect(
      screen.getByText("Calls are recorded as text in the conversation. No audio is kept."),
    ).toBeInTheDocument();
  });

  it("caps the longest call at the organization's maximum", async () => {
    const { onChange } = mount();
    await userEvent.type(screen.getByLabelText("Longest call (minutes)"), "20");
    expect(screen.getByText("At most 10 minutes in this organization.")).toBeInTheDocument();
    expect(onChange).toHaveBeenLastCalledWith({ ...OPENAI, max_call_seconds: 1200 });
  });

  it("stores the longest call in seconds, empty as the organization's, and refuses a non-count", async () => {
    const { onChange } = mount({ value: { ...OPENAI, max_call_seconds: 300 } });
    const field = screen.getByLabelText("Longest call (minutes)");
    expect(field).toHaveValue("5");
    await userEvent.clear(field);
    expect(onChange).toHaveBeenLastCalledWith({ ...OPENAI });
    onChange.mockClear();
    await userEvent.type(field, "x");
    expect(screen.getByText("Enter between 1 and 50 minutes.")).toBeInTheDocument();
    expect(onChange).not.toHaveBeenCalled();
  });

  it("follows a longest call changed underneath", () => {
    const { onChange, view } = mount({ value: { ...OPENAI, max_call_seconds: 300 } });
    view.rerender(
      <VoiceConversationFields
        value={{ ...OPENAI, max_call_seconds: 600 }}
        onChange={onChange}
        capabilityIds={[]}
        hasGuardrails={false}
        orgMaxSeconds={600}
      />,
    );
    expect(screen.getByLabelText("Longest call (minutes)")).toHaveValue("10");
  });

  it("writes the voice note, and an emptied one as null", async () => {
    const { onChange } = mount({ value: { ...OPENAI, voice_note: "x" } });
    const note = screen.getByLabelText("Voice note");
    await userEvent.type(note, "y");
    expect(onChange).toHaveBeenLastCalledWith({ ...OPENAI, voice_note: "xy" });
    await userEvent.clear(note);
    expect(onChange).toHaveBeenLastCalledWith({ ...OPENAI });
  });

  it("shows a provider no longer offered without its fields", () => {
    mount({ value: { ...EMPTY, provider: "gone", model: "m" } });
    expect(screen.getByLabelText("Call provider")).toBeInTheDocument();
    expect(screen.queryByTestId("speech-key-field")).toBeNull();
    expect(screen.queryByLabelText("Voice")).toBeNull();
  });

  it("writes a block that empties out as null", async () => {
    const { onChange } = mount({ value: { ...EMPTY, voice_note: "x" } });
    await userEvent.clear(screen.getByLabelText("Voice note"));
    expect(onChange).toHaveBeenLastCalledWith(null);
  });

  it("waits for a model when a provider has none chosen", () => {
    mount({ value: { ...EMPTY, provider: "openai" } });
    expect(screen.getByLabelText("Call model")).toBeInTheDocument();
    expect(screen.queryByLabelText("Voice")).toBeNull();
  });

  it("locks everything for somebody who may not edit", () => {
    mount({ disabled: true });
    expect(screen.getByRole("switch", { name: "Take voice calls" })).toBeDisabled();
    expect(screen.getByLabelText("Longest call (minutes)")).toBeDisabled();
  });
});
