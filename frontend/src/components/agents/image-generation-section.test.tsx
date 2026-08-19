import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ImageGenerationSection } from "./image-generation-section";
import type { CapabilityBindingSpec, CapabilityCatalogEntry } from "@/types/agents";

/**
 * Whose model draws, and which one.
 *
 * It was one select of whatever the schema enumerated - two entries, written by
 * hand - while OpenAI and Google each ship several image models. Both lists are
 * the server's: whether a provider can draw is `supported_native_tools()` on the
 * SDK, and which models it offers is `app/core/catalog/image_models.json`.
 */

const providers = vi.fn();
vi.mock("@/hooks/use-model-providers", () => ({
  useImageProviders: () => providers(),
}));

const OPENAI = {
  provider: "openai",
  name: "OpenAI",
  models: [
    {
      id: "gpt-image-2",
      name: "GPT Image 2",
      description: "State-of-the-art image generation model.",
    },
    { id: "gpt-image-1-mini", name: "GPT Image 1 mini", description: "Cheapest of the set." },
  ],
};

const GOOGLE = {
  provider: "google",
  name: "Google Gemini",
  models: [{ id: "gemini-3-pro-image", name: "Nano Banana Pro", description: "The most capable." }],
};

const DEFINITION: CapabilityCatalogEntry = {
  id: "image_generation",
  name: "Image generation",
  category: "analysis",
  description: "Generate an image from a text description.",
  side_effecting: true,
  scopes: [],
  tools: [{ id: "generate_image", name: "generate_image", description: "Draw." }],
  contracts: [],
  config_schema: {
    type: "object",
    properties: {
      provider: { type: "string" },
      model: { type: "string" },
      quality: { anyOf: [{ enum: ["low", "high"] }, { type: "null" }], title: "Quality" },
    },
  },
  requires_secret: null,
};

function mount(config: Record<string, unknown> = { provider: "openai", model: "gpt-image-2" }) {
  const onChange = vi.fn();
  render(
    <ImageGenerationSection
      definition={DEFINITION}
      binding={
        {
          id: "image_generation",
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
  providers.mockReturnValue({ providers: [OPENAI, GOOGLE], isLoading: false, isError: false });
});

describe("choosing what draws", () => {
  it("asks for a provider and a model, as two controls", () => {
    mount();

    expect(screen.getByLabelText("Provider")).toHaveTextContent("OpenAI");
    expect(screen.getByLabelText("Model")).toHaveTextContent("GPT Image 2");
  });

  it("says what each model is for, so the choice is not a guess", async () => {
    mount();

    await userEvent.click(screen.getByLabelText("Model"));

    // Every option carries its sentence. Asserted over the options rather than by
    // text, because Radix repeats the chosen one in the closed trigger and the
    // count of nodes holding it is not what this is about.
    const options = await screen.findAllByRole("option");
    expect(options.map((option) => option.textContent)).toEqual([
      "GPT Image 2State-of-the-art image generation model.",
      "GPT Image 1 miniCheapest of the set.",
    ]);
  });

  it("stores the model on its own, beside the provider", async () => {
    const onChange = mount();

    await userEvent.click(screen.getByLabelText("Model"));
    await userEvent.click(await screen.findByRole("option", { name: /GPT Image 1 mini/ }));

    expect(onChange).toHaveBeenCalledWith(
      expect.objectContaining({
        config: expect.objectContaining({ provider: "openai", model: "gpt-image-1-mini" }),
      }),
    );
  });

  it("re-points the model when the provider changes, because an id is not portable", async () => {
    const onChange = mount();

    await userEvent.click(screen.getByLabelText("Provider"));
    await userEvent.click(await screen.findByRole("option", { name: "Google Gemini" }));

    expect(onChange).toHaveBeenCalledWith(
      expect.objectContaining({
        config: expect.objectContaining({ provider: "google", model: "gemini-3-pro-image" }),
      }),
    );
  });

  it("offers only the chosen provider's models", async () => {
    mount({ provider: "google", model: "gemini-3-pro-image" });

    await userEvent.click(screen.getByLabelText("Model"));

    expect(await screen.findByRole("option", { name: /Nano Banana Pro/ })).toBeInTheDocument();
    expect(screen.queryByRole("option", { name: /GPT Image 2/ })).toBeNull();
  });

  it("says so when a stored binding names a provider that cannot draw", () => {
    // A spec written before the check, or by hand. An empty model select with no
    // explanation reads as "this provider has no models".
    mount({ provider: "together", model: "flux-1.1-pro" });

    expect(screen.getByText(/names together, which cannot draw/)).toBeInTheDocument();
  });

  it("shows what an untouched binding will actually draw with", () => {
    // `config: {}` is the shape of a capability somebody has only switched on, and
    // the server resolves both fields from the head of this catalog. Two blank
    // "Choose..." fields for a binding that will draw with OpenAI's first model is
    // the panel disagreeing with the run.
    mount({});

    expect(screen.getByLabelText("Provider")).toHaveTextContent("OpenAI");
    expect(screen.getByLabelText("Model")).toHaveTextContent("GPT Image 2");
  });

  it("shows the provider's first model where only the provider was stored", () => {
    mount({ provider: "google" });

    expect(screen.getByLabelText("Model")).toHaveTextContent("Nano Banana Pro");
  });

  it("still draws the rest of the capability's own fields", () => {
    // Subtracted rather than replaced: a field added to the config appears here
    // without anybody touching this component.
    mount();

    expect(screen.getByLabelText("Quality")).toBeInTheDocument();
  });

  it("carries a change to one of the generated fields through", async () => {
    // The generated form writes to the same config blob as the two selects, so a
    // quality picked here must not clear the model chosen above.
    const onChange = mount();

    await userEvent.click(screen.getByLabelText("Quality"));
    await userEvent.click(await screen.findByRole("option", { name: "high" }));

    expect(onChange).toHaveBeenCalledWith(
      expect.objectContaining({
        config: expect.objectContaining({
          provider: "openai",
          model: "gpt-image-2",
          quality: "high",
        }),
      }),
    );
  });

  it("renders nothing where the deployment never registered the capability", () => {
    // An empty panel reads as something that failed to load.
    const { container } = render(
      <ImageGenerationSection
        definition={undefined}
        binding={{
          id: "image_generation",
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

  it("says it is still reading the list rather than showing an empty one", () => {
    // Between "no providers can draw" and "the answer has not arrived", which are
    // the same empty select and different sentences.
    providers.mockReturnValue({ providers: [], isLoading: true, isError: false });
    mount();

    expect(screen.getByText(/Reading what each provider offers/)).toBeInTheDocument();
  });

  it("says the list could not be read rather than showing an empty picker", () => {
    providers.mockReturnValue({ providers: [], isLoading: false, isError: true });
    mount();

    expect(screen.getByText(/could not be read/)).toBeInTheDocument();
  });
});
