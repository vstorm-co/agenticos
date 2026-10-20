import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { TextToSpeechSection } from "./text-to-speech-section";
import type { CapabilityBindingSpec, CapabilityCatalogEntry } from "@/types/agents";

/**
 * Whose voice, which model, and which of its voices - the image panel's controls
 * plus a voice, so choosing a voice is the same act as choosing a painter (#2259).
 */

const providers = vi.fn();
vi.mock("@/hooks/use-model-providers", () => ({
  useTextToSpeechProviders: () => providers(),
}));

const OPENAI = {
  provider: "openai",
  name: "OpenAI",
  formats: ["mp3", "wav"],
  account_voices: false,
  models: [
    {
      id: "gpt-4o-mini-tts",
      name: "GPT-4o mini TTS",
      description: "Follows style instructions.",
      max_characters: 4096,
      takes_instructions: true,
      voices: [
        { id: "marin", name: "Marin", description: "The most natural." },
        { id: "alloy", name: "Alloy", description: "" },
      ],
    },
    {
      id: "tts-1",
      name: "TTS-1",
      description: "The earlier fast model.",
      max_characters: 4096,
      takes_instructions: false,
      voices: [{ id: "alloy", name: "Alloy", description: "" }],
    },
  ],
};

const ELEVENLABS = {
  provider: "elevenlabs",
  name: "ElevenLabs",
  formats: ["mp3", "wav"],
  account_voices: true,
  models: [
    {
      id: "eleven_v4_turbo",
      name: "Eleven v4 Turbo",
      description: "Top of the rankings.",
      max_characters: 10000,
      takes_instructions: false,
      voices: [],
    },
  ],
};

const DEFINITION: CapabilityCatalogEntry = {
  recommended: null,
  id: "text_to_speech",
  name: "Text to speech",
  category: "analysis",
  description: "Speak a text aloud as an audio clip.",
  side_effecting: true,
  scopes: [],
  tools: [{ id: "generate_speech", name: "generate_speech", description: "Speak." }],
  contracts: [],
  config_schema: {
    type: "object",
    properties: {
      provider: { type: "string" },
      model: { type: "string" },
      voice: { type: "string" },
      max_characters: { type: "integer", title: "Longest text" },
    },
  },
  requires_secret: null,
};

function mount(config: Record<string, unknown> = { provider: "openai", model: "gpt-4o-mini-tts" }) {
  const onChange = vi.fn();
  render(
    <TextToSpeechSection
      definition={DEFINITION}
      binding={
        {
          id: "text_to_speech",
          config,
          approval: "default",
          tool_approval: {},
          tool_overrides: {},
          secret_id: null,
          enabled: true,
        } satisfies CapabilityBindingSpec
      }
      onChange={onChange}
    />,
  );
  return onChange;
}

beforeEach(() => {
  providers.mockReturnValue({ providers: [OPENAI, ELEVENLABS], isLoading: false, isError: false });
});

describe("choosing what speaks", () => {
  it("asks for a provider, a model and a voice, and shows what an untouched binding uses", () => {
    mount({});

    expect(screen.getByLabelText("Provider")).toHaveTextContent("OpenAI");
    expect(screen.getByLabelText("Model")).toHaveTextContent("GPT-4o mini TTS");
    expect(screen.getByLabelText("Voice")).toHaveTextContent("Marin");
  });

  it("offers the voices of the chosen model only", async () => {
    mount({ provider: "openai", model: "tts-1" });

    await userEvent.click(screen.getByLabelText("Voice"));

    const options = await screen.findAllByRole("option");
    expect(options.map((option) => option.textContent)).toEqual(["Alloy"]);
  });

  it("names a voice by what it sounds like where the catalog says", async () => {
    mount();

    await userEvent.click(screen.getByLabelText("Voice"));

    expect(await screen.findByRole("option", { name: "Marin - The most natural." })).toBeVisible();
  });

  it("stores the chosen voice beside the provider and model", async () => {
    const onChange = mount();

    await userEvent.click(screen.getByLabelText("Voice"));
    await userEvent.click(await screen.findByRole("option", { name: "Alloy" }));

    expect(onChange).toHaveBeenCalledWith(
      expect.objectContaining({
        config: expect.objectContaining({ provider: "openai", voice: "alloy" }),
      }),
    );
  });

  it("forgets the voice and format when the provider changes, as neither carries over", async () => {
    const onChange = mount({
      provider: "openai",
      model: "gpt-4o-mini-tts",
      voice: "marin",
      output_format: "wav",
      max_characters: 900,
    });

    await userEvent.click(screen.getByLabelText("Provider"));
    await userEvent.click(await screen.findByRole("option", { name: "ElevenLabs" }));

    expect(onChange).toHaveBeenCalledWith(
      expect.objectContaining({
        config: { provider: "elevenlabs", model: "eleven_v4_turbo", max_characters: 900 },
      }),
    );
  });

  it("keeps the voice when only the model changes", async () => {
    const onChange = mount({ provider: "openai", model: "gpt-4o-mini-tts", voice: "alloy" });

    await userEvent.click(screen.getByLabelText("Model"));
    await userEvent.click(await screen.findByRole("option", { name: /TTS-1/ }));

    expect(onChange).toHaveBeenCalledWith(
      expect.objectContaining({
        config: expect.objectContaining({ model: "tts-1", voice: "alloy" }),
      }),
    );
  });
});

describe("a provider whose voices belong to the account", () => {
  it("asks for the voice id and says why", async () => {
    const onChange = mount({ provider: "elevenlabs", model: "eleven_v4_turbo" });

    expect(screen.getByText(/ElevenLabs voices belong to your account/)).toBeInTheDocument();
    await userEvent.type(screen.getByLabelText("Voice"), "J");

    expect(onChange).toHaveBeenCalledWith(
      expect.objectContaining({ config: expect.objectContaining({ voice: "J" }) }),
    );
  });

  it("shows the stored id", () => {
    mount({ provider: "elevenlabs", model: "eleven_v4_turbo", voice: "JBFqnCBsd6RMkjVDRZzb" });

    expect(screen.getByLabelText("Voice")).toHaveValue("JBFqnCBsd6RMkjVDRZzb");
  });
});

describe("what the panel says about the catalog", () => {
  it("draws no voice control for a provider that cannot speak, and says so", () => {
    mount({ provider: "together", model: "x" });

    expect(screen.getByText(/names together, which cannot speak/)).toBeInTheDocument();
    expect(screen.queryByLabelText("Voice")).toBeNull();
  });

  it("says when the catalog could not be read, or is still being read", () => {
    providers.mockReturnValue({ providers: [], isLoading: true, isError: true });
    mount();

    expect(screen.getByText(/could not be read/)).toBeInTheDocument();
    expect(screen.getByText(/Reading what each provider offers/)).toBeInTheDocument();
  });

  it("still draws the rest of the capability's own fields and carries a change through", async () => {
    const onChange = mount();

    await userEvent.type(screen.getByLabelText("Longest text"), "9");

    expect(onChange).toHaveBeenCalledWith(
      expect.objectContaining({
        config: expect.objectContaining({ provider: "openai", max_characters: 9 }),
      }),
    );
  });

  it("renders nothing where the deployment never registered the capability", () => {
    const { container } = render(
      <TextToSpeechSection
        definition={undefined}
        binding={{
          id: "text_to_speech",
          config: {},
          approval: "default",
          tool_approval: {},
          tool_overrides: {},
          secret_id: null,
          enabled: true,
        }}
        onChange={vi.fn()}
      />,
    );

    expect(container).toBeEmptyDOMElement();
  });
});
