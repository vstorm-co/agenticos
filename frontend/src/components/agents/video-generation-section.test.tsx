import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { VideoGenerationSection } from "./video-generation-section";
import type { CapabilityBindingSpec, CapabilityCatalogEntry } from "@/types/agents";

/**
 * Whose model makes the clip, which one, and at what resolution and shape - the
 * image panel's controls plus the two the chosen model fills in (#2260).
 */

const providers = vi.fn();
vi.mock("@/hooks/use-model-providers", () => ({
  useVideoProviders: () => providers(),
}));

/** The vault, as the key picker reads it. */
const secrets = vi.fn();
vi.mock("@/hooks", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/hooks")>()),
  useSecrets: () => secrets(),
  usePermissions: () => ({ can: () => false }),
}));

const XAI = {
  provider: "xai",
  name: "xAI (Grok)",
  models: [
    {
      id: "grok-imagine-video-1.5",
      name: "Grok Imagine Video 1.5",
      description: "Native 1080p.",
      min_seconds: 1,
      max_seconds: 15,
      duration_choosable: true,
      aspect_ratios: ["16:9", "9:16"],
      resolutions: ["720p", "480p", "1080p"],
      audio: "always" as const,
      first_frame: true,
    },
  ],
};

const GOOGLE = {
  provider: "google",
  name: "Google Gemini",
  models: [
    {
      id: "gemini-omni-1.1-flash",
      name: "Gemini Omni Flash",
      description: "Decides its own length.",
      min_seconds: 3,
      max_seconds: 10,
      duration_choosable: false,
      aspect_ratios: ["16:9", "9:16"],
      resolutions: ["720p", "4k"],
      audio: "always" as const,
      first_frame: true,
    },
  ],
};

const DEFINITION: CapabilityCatalogEntry = {
  recommended: null,
  id: "video_generation",
  name: "Video generation",
  category: "analysis",
  description: "Make a short video from a text description.",
  side_effecting: true,
  scopes: [],
  tools: [{ id: "generate_video", name: "generate_video", description: "Film." }],
  contracts: [],
  config_schema: {
    type: "object",
    properties: {
      provider: { type: "string" },
      model: { type: "string" },
      resolution: { type: "string" },
      aspect_ratio: { type: "string" },
      seconds: { type: "integer", title: "Length" },
      max_seconds: { type: "integer", title: "Longest clip" },
      audio: { anyOf: [{ type: "boolean" }, { type: "null" }], title: "Sound" },
    },
  },
  requires_secret: null,
  voice: "hand_off",
};

function mount(
  config: Record<string, unknown> = { provider: "xai", model: "grok-imagine-video-1.5" },
  definition: CapabilityCatalogEntry = DEFINITION,
  configProblems: { field: string; message: string }[] = [],
  secretId: string | null = null,
) {
  const onChange = vi.fn();
  render(
    <VideoGenerationSection
      definition={definition}
      binding={
        {
          id: "video_generation",
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

const ALIBABA = {
  provider: "alibaba",
  name: "Alibaba Cloud",
  models: [
    {
      id: "wan3.0-video",
      name: "Wan 3.0",
      description: "Optional sound.",
      min_seconds: 2,
      max_seconds: 30,
      duration_choosable: true,
      aspect_ratios: ["16:9"],
      resolutions: ["720p"],
      audio: "optional" as const,
      first_frame: true,
    },
  ],
};

beforeEach(() => {
  providers.mockReturnValue({
    providers: [XAI, GOOGLE, ALIBABA],
    isLoading: false,
    isError: false,
  });
  secrets.mockReturnValue({ secrets: [], isLoading: false, listError: null, create: vi.fn() });
});

describe("choosing what makes the clip", () => {
  it("shows what an untouched binding will make, at the model's first resolution and shape", () => {
    mount({});

    expect(screen.getByLabelText("Provider")).toHaveTextContent("xAI (Grok)");
    expect(screen.getByLabelText("Resolution")).toHaveTextContent("720p");
    expect(screen.getByLabelText("Aspect ratio")).toHaveTextContent("16:9");
    expect(screen.getByText("This model makes clips of 1 to 15 seconds.")).toBeInTheDocument();
  });

  it("offers only the resolutions the chosen model renders", async () => {
    mount({ provider: "google", model: "gemini-omni-1.1-flash" });

    await userEvent.click(screen.getByLabelText("Resolution"));

    const options = await screen.findAllByRole("option");
    expect(options.map((option) => option.textContent)).toEqual(["720p", "4k"]);
    expect(
      screen.getByText("This model decides its own length, 3 to 10 seconds."),
    ).toBeInTheDocument();
  });

  it("stores a resolution and a shape beside the provider and model", async () => {
    const onChange = mount();

    await userEvent.click(screen.getByLabelText("Resolution"));
    await userEvent.click(await screen.findByRole("option", { name: "1080p" }));
    await userEvent.click(screen.getByLabelText("Aspect ratio"));
    await userEvent.click(await screen.findByRole("option", { name: "9:16" }));

    expect(onChange).toHaveBeenCalledWith(
      expect.objectContaining({
        config: expect.objectContaining({ provider: "xai", resolution: "1080p" }),
      }),
    );
    expect(onChange).toHaveBeenCalledWith(
      expect.objectContaining({ config: expect.objectContaining({ aspect_ratio: "9:16" }) }),
    );
  });

  it("shows a stored value the model renders, and the model's first for one it does not", () => {
    mount({
      provider: "xai",
      model: "grok-imagine-video-1.5",
      resolution: "1080p",
      aspect_ratio: "4:3",
    });

    expect(screen.getByLabelText("Resolution")).toHaveTextContent("1080p");
    expect(screen.getByLabelText("Aspect ratio")).toHaveTextContent("16:9");
  });

  it("forgets what was chosen for one model when the provider changes", async () => {
    const onChange = mount({
      provider: "xai",
      model: "grok-imagine-video-1.5",
      resolution: "1080p",
      seconds: 8,
      timeout_seconds: 900,
    });

    await userEvent.click(screen.getByLabelText("Provider"));
    await userEvent.click(await screen.findByRole("option", { name: "Google Gemini" }));

    expect(onChange).toHaveBeenCalledWith(
      expect.objectContaining({
        config: { provider: "google", model: "gemini-omni-1.1-flash", timeout_seconds: 900 },
      }),
    );
  });
});

describe("what the panel says about the catalog", () => {
  it("draws no resolution for a provider that cannot make video, and says so", () => {
    mount({ provider: "together", model: "x" });

    expect(screen.getByText(/names together, which cannot make video/)).toBeInTheDocument();
    expect(screen.queryByLabelText("Resolution")).toBeNull();
  });

  it("says when the catalog could not be read, or is still being read", () => {
    providers.mockReturnValue({ providers: [], isLoading: true, isError: true });
    mount();

    expect(screen.getByText(/could not be read/)).toBeInTheDocument();
    expect(screen.getByText(/Reading what each provider offers/)).toBeInTheDocument();
  });

  it("still draws the rest of the capability's own fields and carries a change through", async () => {
    const onChange = mount();

    await userEvent.type(screen.getByLabelText("Length"), "7");

    expect(onChange).toHaveBeenCalledWith(
      expect.objectContaining({ config: expect.objectContaining({ provider: "xai", seconds: 7 }) }),
    );
  });

  it("renders nothing where the deployment never registered the capability", () => {
    const { container } = render(
      <VideoGenerationSection
        definition={undefined}
        binding={{
          id: "video_generation",
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

describe("what a model leaves to the author", () => {
  it("offers sound in three states only where the model makes it optional", async () => {
    const onChange = mount({ provider: "alibaba", model: "wan3.0-video", audio: false });

    expect(screen.getByLabelText("Sound")).toHaveTextContent("Off");
    await userEvent.click(screen.getByLabelText("Sound"));
    await userEvent.click(await screen.findByRole("option", { name: "On" }));
    expect(onChange).toHaveBeenLastCalledWith(
      expect.objectContaining({
        config: { provider: "alibaba", model: "wan3.0-video", audio: true },
      }),
    );

    await userEvent.click(screen.getByLabelText("Sound"));
    await userEvent.click(await screen.findByRole("option", { name: "Provider default" }));
    expect(onChange).toHaveBeenLastCalledWith(
      expect.objectContaining({ config: { provider: "alibaba", model: "wan3.0-video" } }),
    );
  });

  it("shows the provider default for an untouched binding, rather than Off", () => {
    mount({ provider: "alibaba", model: "wan3.0-video" });
    expect(screen.getByLabelText("Sound")).toHaveTextContent("Provider default");
  });

  it("shows On for a binding that turned sound on", () => {
    mount({ provider: "alibaba", model: "wan3.0-video", audio: true });
    expect(screen.getByLabelText("Sound")).toHaveTextContent("On");
  });

  it("draws no sound control for a model whose sound is fixed", () => {
    mount();

    expect(screen.queryByLabelText("Sound")).toBeNull();
  });

  it("draws no length fields for a model that decides its own length", () => {
    mount({ provider: "google", model: "gemini-omni-1.1-flash" });

    expect(screen.queryByLabelText("Length")).toBeNull();
    expect(screen.queryByLabelText("Longest clip")).toBeNull();
  });

  it("draws the length fields for a model that takes one", () => {
    mount();

    expect(screen.getByLabelText("Length")).toBeInTheDocument();
    expect(screen.getByLabelText("Longest clip")).toBeInTheDocument();
  });
});

describe("the key it renders with", () => {
  it("asks for the default provider's key before any provider is picked", async () => {
    // `config: {}` runs on the catalog's first provider, which needs a key: the
    // picker read the condition against the stored config and stayed hidden
    // while publish refused the spec for the key it gave no way to choose.
    secrets.mockReturnValue({
      secrets: [
        {
          id: "sec-xai",
          name: "xai key",
          description: null,
          kind: "api_key",
          hint: "abcd",
          purpose: "xai",
        },
        {
          id: "sec-goog",
          name: "google key",
          description: null,
          kind: "api_key",
          hint: "abcd",
          purpose: "google",
        },
      ],
      isLoading: false,
      listError: null,
      create: vi.fn(),
    });
    const onChange = mount(
      {},
      {
        ...DEFINITION,
        requires_secret: {
          kind: "api_key",
          description: "The API key for the chosen video provider",
          required_when: { field: "provider", equals: ["xai", "google", "alibaba"] },
          purpose: null,
        },
      },
    );

    await userEvent.click(screen.getByLabelText("Secret"));

    expect(screen.queryByRole("option", { name: /google key/ })).toBeNull();
    await userEvent.click(screen.getByRole("option", { name: /xai key/ }));
    expect(onChange).toHaveBeenCalledWith(
      expect.objectContaining({ secret_id: "sec-xai", config: { provider: "xai" } }),
    );
  });
});

describe("the highest resolution the agent may ask for", () => {
  it("offers the usual resolution and what is taller, and any as the default", async () => {
    mount({ provider: "xai", model: "grok-imagine-video-1.5", resolution: "720p" });

    expect(screen.getByLabelText("Highest resolution")).toHaveTextContent("Any resolution");
    await userEvent.click(screen.getByLabelText("Highest resolution"));

    const options = await screen.findAllByRole("option");
    expect(options.map((option) => option.textContent)).toEqual([
      "Any resolution",
      "720p",
      "1080p",
    ]);
  });

  it("warns that with no ceiling any resolution may be asked for", () => {
    mount({ provider: "xai", model: "grok-imagine-video-1.5" });

    expect(
      screen.getByText(/the agent may ask for any resolution this model renders, up to 1080p/),
    ).toBeInTheDocument();
  });

  it("drops the warning once there is a ceiling", () => {
    mount({ provider: "xai", model: "grok-imagine-video-1.5", max_resolution: "720p" });

    expect(screen.getByLabelText("Highest resolution")).toHaveTextContent("720p");
    expect(screen.queryByText(/may ask for any resolution/)).toBeNull();
  });

  it("says each setting above is a default the agent may override", () => {
    mount({ provider: "alibaba", model: "wan3.0-video", audio: true });

    expect(screen.getByText(/may ask for another per clip, up to the highest/)).toBeInTheDocument();
    expect(screen.getByText(/may ask for another shape/)).toBeInTheDocument();
    expect(screen.getByText(/may ask for sound on or off/)).toBeInTheDocument();
    // One resolution: nothing to warn about.
    expect(screen.queryByText(/may ask for any resolution/)).toBeNull();
  });

  it("stores a ceiling, and clears it again", async () => {
    const onChange = mount({ provider: "xai", model: "grok-imagine-video-1.5" });

    await userEvent.click(screen.getByLabelText("Highest resolution"));
    await userEvent.click(await screen.findByRole("option", { name: "1080p" }));

    expect(onChange).toHaveBeenLastCalledWith(
      expect.objectContaining({
        config: { provider: "xai", model: "grok-imagine-video-1.5", max_resolution: "1080p" },
      }),
    );
  });

  it("drops the ceiling when any resolution is chosen again", async () => {
    const onChange = mount({
      provider: "xai",
      model: "grok-imagine-video-1.5",
      max_resolution: "1080p",
    });

    expect(screen.getByLabelText("Highest resolution")).toHaveTextContent("1080p");
    await userEvent.click(screen.getByLabelText("Highest resolution"));
    await userEvent.click(await screen.findByRole("option", { name: "Any resolution" }));

    expect(onChange).toHaveBeenLastCalledWith(
      expect.objectContaining({ config: { provider: "xai", model: "grok-imagine-video-1.5" } }),
    );
  });

  it("drops a ceiling the new usual resolution reaches", async () => {
    // The server refuses a usual resolution above the highest: the ceiling goes
    // rather than leaving a binding that cannot be published.
    const onChange = mount({
      provider: "xai",
      model: "grok-imagine-video-1.5",
      resolution: "480p",
      max_resolution: "720p",
    });

    await userEvent.click(screen.getByLabelText("Resolution"));
    await userEvent.click(await screen.findByRole("option", { name: "1080p" }));
    expect(onChange).toHaveBeenLastCalledWith(
      expect.objectContaining({
        config: { provider: "xai", model: "grok-imagine-video-1.5", resolution: "1080p" },
      }),
    );
  });

  it("keeps a ceiling still above the new usual resolution", async () => {
    const onChange = mount({
      provider: "xai",
      model: "grok-imagine-video-1.5",
      resolution: "480p",
      max_resolution: "1080p",
    });

    await userEvent.click(screen.getByLabelText("Resolution"));
    await userEvent.click(await screen.findByRole("option", { name: "720p" }));
    expect(onChange).toHaveBeenLastCalledWith(
      expect.objectContaining({
        config: expect.objectContaining({ resolution: "720p", max_resolution: "1080p" }),
      }),
    );
  });

  it("does not carry a ceiling onto another model", async () => {
    const onChange = mount({
      provider: "xai",
      model: "grok-imagine-video-1.5",
      max_resolution: "1080p",
    });

    await userEvent.click(screen.getByLabelText("Provider"));
    await userEvent.click(await screen.findByRole("option", { name: /Google Gemini/ }));

    expect(onChange.mock.lastCall?.[0].config).not.toHaveProperty("max_resolution");
  });
});

describe("what publish refused, and the key", () => {
  it("forgets the key when the provider changes, so one provider's key is not sent to the next", async () => {
    const onChange = mount(
      { provider: "xai", model: "grok-imagine-video-1.5" },
      DEFINITION,
      [],
      "sec-xai",
    );

    await userEvent.click(screen.getByLabelText("Provider"));
    await userEvent.click(await screen.findByRole("option", { name: /Google Gemini/ }));

    expect(onChange.mock.lastCall?.[0].config).not.toHaveProperty("max_resolution");

    expect(onChange.mock.lastCall?.[0].secret_id).toBeNull();
  });

  it("keeps the key when only the model changes", async () => {
    const lite = { ...XAI.models[0], id: "grok-imagine-video-1.5-lite", name: "Grok Lite" };
    providers.mockReturnValue({
      providers: [{ ...XAI, models: [...XAI.models, lite] }, GOOGLE, ALIBABA],
      isLoading: false,
      isError: false,
    });
    const onChange = mount(
      { provider: "xai", model: "grok-imagine-video-1.5" },
      DEFINITION,
      [],
      "sec-xai",
    );

    await userEvent.click(screen.getByLabelText("Model"));
    await userEvent.click(await screen.findByRole("option", { name: /Grok Lite/ }));

    expect(onChange.mock.lastCall?.[0].secret_id).toBe("sec-xai");
  });

  it("says what publish refused about a control the panel draws itself", () => {
    mount({ provider: "xai", model: "grok-imagine-video-1.5", resolution: "4k" }, DEFINITION, [
      {
        field: "capabilities.video_generation.config.resolution",
        message: "grok-imagine-video-1.5 renders 720p, 480p, 1080p, not 4k.",
      },
    ]);

    expect(screen.getByText(/renders 720p, 480p, 1080p, not 4k/)).toBeInTheDocument();
  });

  it("says a refused length the form does not show for a model that decides its own", () => {
    mount({ provider: "google", model: "gemini-omni-1.1-flash", seconds: 5 }, DEFINITION, [
      {
        field: "capabilities.video_generation.config.seconds",
        message: "gemini-omni-1.1-flash decides its own length, so a length has no effect.",
      },
    ]);

    expect(
      screen.getByText(/decides its own length, so a length has no effect/),
    ).toBeInTheDocument();
  });
});
