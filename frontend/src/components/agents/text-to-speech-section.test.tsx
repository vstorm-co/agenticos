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

/** The vault, as the key picker reads it. */
const secrets = vi.fn();
vi.mock("@/hooks", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/hooks")>()),
  useSecrets: () => secrets(),
  usePermissions: () => ({ can: () => false }),
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
  voice: "live",
};

function mount(
  config: Record<string, unknown> = { provider: "openai", model: "gpt-4o-mini-tts" },
  definition: CapabilityCatalogEntry = DEFINITION,
  configProblems: { field: string; message: string }[] = [],
  secretId: string | null = null,
) {
  const onChange = vi.fn();
  render(
    <TextToSpeechSection
      definition={definition}
      binding={
        {
          id: "text_to_speech",
          config,
          approval: "default",
          tool_approval: {},
          tool_overrides: {},
          secret_id: secretId,
          enabled: true,
        } satisfies CapabilityBindingSpec
      }
      onChange={onChange}
      configProblems={configProblems}
    />,
  );
  return onChange;
}

beforeEach(() => {
  providers.mockReturnValue({ providers: [OPENAI, ELEVENLABS], isLoading: false, isError: false });
  secrets.mockReturnValue({ secrets: [], isLoading: false, listError: null, create: vi.fn() });
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

  it("forgets the key when the provider changes, so one provider's key is not sent to the next", async () => {
    const onChange = mount(
      { provider: "openai", model: "gpt-4o-mini-tts" },
      DEFINITION,
      [],
      "sec-openai",
    );

    await userEvent.click(screen.getByLabelText("Provider"));
    await userEvent.click(await screen.findByRole("option", { name: "ElevenLabs" }));

    expect(onChange.mock.lastCall?.[0].secret_id).toBeNull();
  });

  it("keeps the key when only the model changes", async () => {
    const onChange = mount(
      { provider: "openai", model: "gpt-4o-mini-tts" },
      DEFINITION,
      [],
      "sec-openai",
    );

    await userEvent.click(screen.getByLabelText("Model"));
    await userEvent.click(await screen.findByRole("option", { name: /TTS-1/ }));

    expect(onChange.mock.lastCall?.[0].secret_id).toBe("sec-openai");
  });

  it("says what publish refused about a control the panel draws itself", () => {
    mount({ provider: "openai", model: "tts-9" }, DEFINITION, [
      { field: "capabilities.text_to_speech.config.model", message: "openai/tts-9 cannot speak." },
    ]);

    expect(screen.getByText("openai/tts-9 cannot speak.")).toBeInTheDocument();
  });

  it("drops a voice the newly chosen model does not speak in", async () => {
    // `tts-1` speaks in nine of OpenAI's voices, and `marin` is not one of them;
    // keeping it would leave the select showing Alloy while publish refused marin.
    const onChange = mount({ provider: "openai", model: "gpt-4o-mini-tts", voice: "marin" });

    await userEvent.click(screen.getByLabelText("Model"));
    await userEvent.click(await screen.findByRole("option", { name: /TTS-1/ }));

    expect(onChange).toHaveBeenCalledWith(
      expect.objectContaining({ config: { provider: "openai", model: "tts-1" } }),
    );
  });

  it("offers only the formats the provider returns, and stores the one chosen", async () => {
    const onChange = mount();

    expect(screen.getByLabelText("File format")).toHaveTextContent("mp3");
    await userEvent.click(screen.getByLabelText("File format"));
    await userEvent.click(await screen.findByRole("option", { name: "wav" }));

    expect(onChange).toHaveBeenCalledWith(
      expect.objectContaining({ config: expect.objectContaining({ output_format: "wav" }) }),
    );
  });

  it("shows a stored format, and the provider's first for one it does not return", () => {
    mount({ provider: "openai", model: "gpt-4o-mini-tts", output_format: "wav" });
    expect(screen.getByLabelText("File format")).toHaveTextContent("wav");
  });

  it("locks the format where the provider returns only one", () => {
    providers.mockReturnValue({
      providers: [{ ...OPENAI, formats: ["wav"] }],
      isLoading: false,
      isError: false,
    });
    mount({ provider: "openai", model: "gpt-4o-mini-tts", output_format: "mp3" });

    expect(screen.getByLabelText("File format")).toHaveTextContent("wav");
    expect(screen.getByLabelText("File format")).toBeDisabled();
  });

  it("keeps an account voice id when the model changes on the same provider", async () => {
    // ElevenLabs lists no voices - they belong to the account - so the id cannot
    // be checked against the new model's list and must survive the switch.
    providers.mockReturnValue({
      providers: [
        OPENAI,
        {
          ...ELEVENLABS,
          models: [
            ...ELEVENLABS.models,
            { ...ELEVENLABS.models[0], id: "eleven_v4", name: "Eleven v4" },
          ],
        },
      ],
      isLoading: false,
      isError: false,
    });
    const onChange = mount({ provider: "elevenlabs", model: "eleven_v4_turbo", voice: "JBFq" });

    await userEvent.click(screen.getByLabelText("Model"));
    await userEvent.click(await screen.findByRole("option", { name: /^Eleven v4Top/ }));

    expect(onChange).toHaveBeenCalledWith(
      expect.objectContaining({
        config: { provider: "elevenlabs", model: "eleven_v4", voice: "JBFq" },
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

describe("the key it speaks with", () => {
  /** As the server declares it: every provider needs a key of its own purpose. */
  const KEYED: CapabilityCatalogEntry = {
    ...DEFINITION,
    requires_secret: {
      kind: "api_key",
      description: "The API key for the chosen speech provider",
      required_when: { field: "provider", equals: ["openai", "elevenlabs"] },
      purpose: null,
    },
  };
  const key = (id: string, purpose: string) => ({
    id,
    name: `${purpose} key`,
    description: null,
    kind: "api_key",
    hint: "abcd",
    purpose,
  });

  it("asks for the default provider's key before any provider is picked", async () => {
    // `config: {}` is what switching the capability on stores, and the server
    // resolves it to the catalog's first provider - which needs a key. Reading the
    // condition against the stored config hid the picker while publish refused
    // the spec for the key it gave no way to choose.
    secrets.mockReturnValue({
      secrets: [key("sec-openai", "openai"), key("sec-eleven", "elevenlabs")],
      isLoading: false,
      listError: null,
      create: vi.fn(),
    });
    const onChange = mount({}, KEYED);

    await userEvent.click(screen.getByLabelText("Secret"));

    expect(screen.queryByRole("option", { name: /elevenlabs key/ })).toBeNull();
    await userEvent.click(screen.getByRole("option", { name: /openai key/ }));
    // The provider the key is for is stored with it, so a catalog reordered later
    // cannot move this key onto another provider's API.
    expect(onChange).toHaveBeenCalledWith(
      expect.objectContaining({ secret_id: "sec-openai", config: { provider: "openai" } }),
    );
  });

  it("leaves a provider somebody stored alone", async () => {
    mount({ provider: "elevenlabs", model: "eleven_v4_turbo" }, KEYED);

    expect(screen.getByLabelText("Secret")).toHaveTextContent("No api_key secret in the vault");
  });
});

describe("the other voices the agent may choose", () => {
  it("warns that with none ticked any of the model's voices may speak", () => {
    mount({ provider: "openai", model: "gpt-4o-mini-tts" });

    expect(
      screen.getByText("None allowed: the agent may speak in any of this model's 2 voices."),
    ).toBeInTheDocument();
    expect(screen.getByText(/The default - the agent may switch to another/)).toBeInTheDocument();
  });

  it("offers the model's voices but the usual one, and stores the ticked ones", async () => {
    const onChange = mount({ provider: "openai", model: "gpt-4o-mini-tts", voice: "marin" });

    expect(screen.queryByRole("checkbox", { name: "Marin" })).toBeNull();
    await userEvent.click(screen.getByRole("checkbox", { name: "Alloy" }));

    expect(onChange).toHaveBeenLastCalledWith(
      expect.objectContaining({
        config: expect.objectContaining({ voices: [{ id: "alloy" }] }),
      }),
    );
  });

  it("says when the agent has as many as it may be offered, and keeps the ticked ones live", () => {
    // Gemini has thirty voices to tick; the server takes twenty.
    const many = Array.from({ length: 21 }, (_, at) => ({
      id: `v${at}`,
      name: `Voice ${at}`,
      description: "",
    }));
    providers.mockReturnValue({
      providers: [{ ...OPENAI, models: [{ ...OPENAI.models[0], voices: many }] }],
      isLoading: false,
      isError: false,
    });
    mount({
      provider: "openai",
      model: "gpt-4o-mini-tts",
      voice: "v0",
      voices: many
        .slice(1, 20)
        .map(({ id }) => ({ id }))
        .concat({ id: "v20" }),
    });

    expect(screen.getByRole("checkbox", { name: "Voice 1" })).toBeEnabled();
    expect(
      screen.getByText("20 other voices is the most one agent can be offered."),
    ).toBeInTheDocument();
  });

  it("disables what is left unticked at the limit", () => {
    const many = Array.from({ length: 22 }, (_, at) => ({
      id: `v${at}`,
      name: `Voice ${at}`,
      description: "",
    }));
    providers.mockReturnValue({
      providers: [{ ...OPENAI, models: [{ ...OPENAI.models[0], voices: many }] }],
      isLoading: false,
      isError: false,
    });
    mount({
      provider: "openai",
      model: "gpt-4o-mini-tts",
      voice: "v0",
      voices: many.slice(1, 21).map(({ id }) => ({ id })),
    });

    expect(screen.getByRole("checkbox", { name: "Voice 21" })).toBeDisabled();
    expect(screen.getByRole("checkbox", { name: "Voice 20" })).toBeEnabled();
  });

  it("takes a new usual voice out of the others, where it could not be seen", async () => {
    const onChange = mount({
      provider: "openai",
      model: "gpt-4o-mini-tts",
      voice: "marin",
      voices: [{ id: "alloy" }],
    });

    await userEvent.click(screen.getByLabelText("Voice"));
    await userEvent.click(await screen.findByRole("option", { name: /^Alloy/ }));

    expect(onChange.mock.lastCall?.[0].config).toEqual({
      provider: "openai",
      model: "gpt-4o-mini-tts",
      voice: "alloy",
    });
  });

  it("takes the voice a new model speaks in by default out of the others", async () => {
    // `tts-1` has no Marin, so its usual voice becomes its first: Alloy.
    const onChange = mount({
      provider: "openai",
      model: "gpt-4o-mini-tts",
      voice: "marin",
      voices: [{ id: "alloy" }],
    });

    await userEvent.click(screen.getByLabelText("Model"));
    await userEvent.click(await screen.findByRole("option", { name: /TTS-1/ }));

    expect(onChange.mock.lastCall?.[0].config).toEqual({ provider: "openai", model: "tts-1" });
  });

  it("lists what publish refused about a ticked voice, which has no row to mark", () => {
    mount({ provider: "openai", model: "gpt-4o-mini-tts", voices: [{ id: "alloy" }] }, DEFINITION, [
      {
        field: "capabilities.text_to_speech.config.voices.0.id",
        message: "This voice is listed already.",
      },
    ]);

    expect(screen.getByText("This voice is listed already.")).toBeInTheDocument();
  });

  it("says what publish refused about the list", () => {
    mount({ provider: "openai", model: "gpt-4o-mini-tts" }, DEFINITION, [
      {
        field: "capabilities.text_to_speech.config.voices",
        message: "List should have at most 20 items",
      },
    ]);

    expect(screen.getByText("List should have at most 20 items")).toBeInTheDocument();
  });

  it("unticking the last one stores no list at all", async () => {
    const onChange = mount({
      provider: "openai",
      model: "gpt-4o-mini-tts",
      voices: [{ id: "alloy" }],
    });

    expect(screen.getByRole("checkbox", { name: "Alloy" })).toBeChecked();
    await userEvent.click(screen.getByRole("checkbox", { name: "Alloy" }));

    expect(onChange.mock.lastCall?.[0].config).toEqual({
      provider: "openai",
      model: "gpt-4o-mini-tts",
    });
  });

  it("keeps the voices the next model still speaks in, and drops the rest", async () => {
    // `tts-1` here has Alloy and Echo but not Marin, so only Echo can stay on offer
    // beside the usual Alloy.
    const echo = { id: "echo", name: "Echo", description: "" };
    providers.mockReturnValue({
      providers: [
        {
          ...OPENAI,
          models: OPENAI.models.map((model) =>
            model.id === "tts-1" ? { ...model, voices: [...model.voices, echo] } : model,
          ),
        },
        ELEVENLABS,
      ],
      isLoading: false,
      isError: false,
    });
    const onChange = mount({
      provider: "openai",
      model: "gpt-4o-mini-tts",
      voice: "alloy",
      voices: [{ id: "marin" }, { id: "echo" }, "junk"],
    });

    await userEvent.click(screen.getByLabelText("Model"));
    await userEvent.click(await screen.findByRole("option", { name: /TTS-1/ }));

    expect(onChange.mock.lastCall?.[0].config).toEqual({
      provider: "openai",
      model: "tts-1",
      voice: "alloy",
      voices: [{ id: "echo" }],
    });
  });

  it("drops every other voice with the provider", async () => {
    const onChange = mount({
      provider: "openai",
      model: "gpt-4o-mini-tts",
      voices: [{ id: "alloy" }],
    });

    await userEvent.click(screen.getByLabelText("Provider"));
    await userEvent.click(await screen.findByRole("option", { name: /ElevenLabs/ }));

    expect(onChange.mock.lastCall?.[0].config).not.toHaveProperty("voices");
  });

  describe("on a provider whose voices belong to the account", () => {
    const account = (voices: unknown[] = []) =>
      mount({ provider: "elevenlabs", model: "eleven_v4_turbo", voice: "narrator1", voices });

    it("adds a row to type a voice id into", async () => {
      const onChange = account();

      await userEvent.click(screen.getByRole("button", { name: "Add a voice" }));

      expect(onChange.mock.lastCall?.[0].config.voices).toEqual([{ id: "" }]);
    });

    it("stores the id and the note each row holds", async () => {
      const onChange = account([{ id: "villain2", note: "Igor" }, { id: "extra3" }]);

      await userEvent.type(screen.getByLabelText("Voice id 1"), "x");
      expect(onChange.mock.lastCall?.[0].config.voices).toEqual([
        { id: "villain2x", note: "Igor" },
        { id: "extra3" },
      ]);

      await userEvent.clear(screen.getByLabelText("What voice 1 is for"));
      expect(onChange.mock.lastCall?.[0].config.voices).toEqual([
        { id: "villain2", note: null },
        { id: "extra3" },
      ]);
    });

    it("marks the row publish refused, and says why", () => {
      mount(
        { provider: "elevenlabs", model: "eleven_v4_turbo", voice: "n1", voices: [{ id: "" }] },
        DEFINITION,
        [
          {
            field: "capabilities.text_to_speech.config.voices.0.id",
            message: "String should have at least 1 character",
          },
        ],
      );

      expect(screen.getByLabelText("Voice id 1")).toHaveAttribute("aria-invalid", "true");
      expect(screen.getByText("String should have at least 1 character")).toBeInTheDocument();
    });

    it("marks a note publish refused", () => {
      mount(
        { provider: "elevenlabs", model: "eleven_v4_turbo", voice: "n1", voices: [{ id: "v2" }] },
        DEFINITION,
        [{ field: "capabilities.text_to_speech.config.voices.0.note", message: "Too long" }],
      );

      expect(screen.getByLabelText("What voice 1 is for")).toHaveAttribute("aria-invalid", "true");
      expect(screen.getByText("Too long")).toBeInTheDocument();
    });

    it("warns that with none listed any voice in the account may speak", () => {
      account();

      expect(screen.queryByRole("checkbox")).toBeNull();
      expect(
        screen.getByText(/any voice in your ElevenLabs account by its id - cloned voices included/),
      ).toBeInTheDocument();
    });

    it("drops the warning once a voice is listed", () => {
      account([{ id: "villain2" }]);

      expect(screen.queryByText(/cloned voices included/)).toBeNull();
    });

    it("removes a row", async () => {
      const onChange = account([{ id: "villain2" }, { id: "extra3" }]);

      await userEvent.click(screen.getByRole("button", { name: "Remove voice 1" }));

      expect(onChange.mock.lastCall?.[0].config.voices).toEqual([{ id: "extra3" }]);
    });

    it("stops adding at the most one agent may be offered", () => {
      account(Array.from({ length: 20 }, (_, at) => ({ id: `voice${at}` })));

      expect(screen.getByRole("button", { name: "Add a voice" })).toBeDisabled();
    });

    it("keeps every other voice across the provider's models", async () => {
      // The catalog lists no account voices, so none can be known to be missing.
      const flash = { ...ELEVENLABS.models[0], id: "eleven_flash_v2_5", name: "Eleven Flash" };
      providers.mockReturnValue({
        providers: [OPENAI, { ...ELEVENLABS, models: [...ELEVENLABS.models, flash] }],
        isLoading: false,
        isError: false,
      });
      const onChange = account([{ id: "villain2" }]);

      await userEvent.click(screen.getByLabelText("Model"));
      await userEvent.click(await screen.findByRole("option", { name: /Eleven Flash/ }));

      expect(onChange.mock.lastCall?.[0].config.voices).toEqual([{ id: "villain2" }]);
    });
  });
});
