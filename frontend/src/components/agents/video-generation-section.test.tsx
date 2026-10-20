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
    },
  },
  requires_secret: null,
};

function mount(
  config: Record<string, unknown> = { provider: "xai", model: "grok-imagine-video-1.5" },
) {
  const onChange = vi.fn();
  render(
    <VideoGenerationSection
      definition={DEFINITION}
      binding={
        {
          id: "video_generation",
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
  providers.mockReturnValue({ providers: [XAI, GOOGLE], isLoading: false, isError: false });
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
