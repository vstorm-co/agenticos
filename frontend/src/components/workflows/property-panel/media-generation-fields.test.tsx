import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render as renderView, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type {
  ImageProvider,
  ImageWorkflowSupport,
  VideoProvider,
} from "@/hooks/use-model-providers";
import { MediaGenerationFields, type MediaGenerationNode } from "./media-generation-fields";

function render(view: ReactNode) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return renderView(view, {
    wrapper: ({ children }) => (
      <QueryClientProvider client={client}>{children}</QueryClientProvider>
    ),
  });
}

const imageCatalog = vi.fn();
const videoCatalog = vi.fn();
const vault = vi.fn();
const callbacks = vi.hoisted(() => ({
  offering: undefined as undefined | ((patch: { provider?: string; model: string }) => void),
  secret: undefined as undefined | ((value: string | null) => void),
}));

vi.mock("@/hooks/use-model-providers", () => ({
  useImageProviders: () => imageCatalog(),
  useVideoProviders: () => videoCatalog(),
}));
vi.mock("@/hooks", () => ({
  useSecrets: () => vault(),
  usePermissions: () => ({ can: () => false }),
}));
vi.mock("@/components/agents/provider-model-fields", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/components/agents/provider-model-fields")>();
  return {
    ...actual,
    ProviderModelFields: (props: Parameters<typeof actual.ProviderModelFields>[0]) => {
      callbacks.offering = props.onChange;
      return <actual.ProviderModelFields {...props} />;
    },
  };
});
vi.mock("@/components/workflows/pickers/secret-picker", async (importOriginal) => {
  const actual =
    await importOriginal<typeof import("@/components/workflows/pickers/secret-picker")>();
  return {
    ...actual,
    SecretPicker: (props: Parameters<typeof actual.SecretPicker>[0]) => {
      callbacks.secret = props.onChange;
      return <actual.SecretPicker {...props} />;
    },
  };
});

const SUPPORT: ImageWorkflowSupport = {
  reference_image: true,
  qualities: [],
  sizes: ["1K", "2K"],
  aspect_ratios: ["1:1", "16:9"],
  backgrounds: [],
  output_formats: [],
  defaults: {
    quality: null,
    size: "1K",
    aspect_ratio: "1:1",
    background: null,
    output_format: null,
  },
  max_input_tokens: 100,
  max_output_tokens: 50,
  input_usd_per_million: "2",
  output_usd_per_million: "10",
  tool_prompt_max_characters: 0,
  tool_input_usd_per_million: "0",
  output_prices: [],
  pricing_as_of: "2026-11-16",
  sources: ["https://example.test/model-pricing"],
};

const IMAGES: ImageProvider[] = [
  {
    provider: "google",
    name: "Google",
    models: [
      { id: "image-one", name: "Image One", description: "Reference drawing.", workflow: SUPPORT },
      {
        id: "image-two",
        name: "Image Two",
        description: "Another drawing.",
        workflow: { ...SUPPORT, defaults: { ...SUPPORT.defaults, size: "2K" } },
      },
      { id: "old-image", name: "Legacy image", description: "Agent only.", workflow: null },
      { id: "no-workflow", name: "No workflow", description: "No workflow contract." },
    ],
  },
  {
    provider: "openai",
    name: "OpenAI",
    models: [
      {
        id: "text-image",
        name: "Text image",
        description: "Text-only drawing.",
        workflow: {
          ...SUPPORT,
          reference_image: false,
          qualities: ["low", "high"],
          sizes: ["1024x1024"],
          aspect_ratios: [],
          backgrounds: ["opaque", "transparent"],
          output_formats: ["png", "webp"],
          defaults: {
            quality: "low",
            size: "1024x1024",
            aspect_ratio: null,
            background: "opaque",
            output_format: "png",
          },
        },
      },
    ],
  },
  {
    provider: "unavailable",
    name: "Agent-only provider",
    models: [{ id: "legacy", name: "Legacy", description: "Agent only." }],
  },
];

const VIDEOS: VideoProvider[] = [
  {
    provider: "xai",
    name: "xAI",
    models: [
      {
        id: "clip",
        name: "Clip",
        description: "Optional sound.",
        min_seconds: 2,
        max_seconds: 12,
        duration_choosable: true,
        resolutions: ["720p", "1080p"],
        aspect_ratios: ["16:9", "9:16"],
        audio: "optional",
        first_frame: true,
        workflow: {
          reference_image: true,
          pricing_as_of: "2026-11-16",
          usd_per_second: { "720p": "0.1", "1080p": "0.2" },
          defaults: { resolution: "720p", aspect_ratio: "16:9", seconds: 5, audio: false },
        },
      },
      {
        id: "automatic",
        name: "Automatic",
        description: "Chooses its length.",
        min_seconds: 3,
        max_seconds: 10,
        duration_choosable: false,
        resolutions: ["720p"],
        aspect_ratios: ["16:9"],
        audio: "always",
        first_frame: false,
        workflow: {
          reference_image: false,
          pricing_as_of: "2026-11-16",
          usd_per_second: { "720p": "0.2" },
          defaults: { resolution: "720p", aspect_ratio: "16:9", seconds: null, audio: null },
        },
      },
      {
        id: "silent",
        name: "Silent",
        description: "No sound.",
        min_seconds: 2,
        max_seconds: 6,
        duration_choosable: true,
        resolutions: ["480p"],
        aspect_ratios: ["1:1"],
        audio: "never",
        first_frame: true,
        workflow: {
          reference_image: true,
          pricing_as_of: "2026-11-16",
          usd_per_second: { "480p": "0.1" },
          defaults: { resolution: "480p", aspect_ratio: "1:1", seconds: 4, audio: null },
        },
      },
      {
        id: "legacy-video",
        name: "Legacy video",
        description: "Agent only.",
        min_seconds: 1,
        max_seconds: 2,
        duration_choosable: true,
        resolutions: ["720p"],
        aspect_ratios: ["16:9"],
        audio: "never",
        first_frame: false,
        workflow: null,
      },
    ],
  },
];

beforeEach(() => {
  vi.clearAllMocks();
  imageCatalog.mockReturnValue({ providers: IMAGES, isLoading: false, isError: false });
  videoCatalog.mockReturnValue({ providers: VIDEOS, isLoading: false, isError: false });
  vault.mockReturnValue({
    secrets: [
      {
        id: "org-google",
        name: "Team Google",
        kind: "api_key",
        purpose: "google",
        usage_scope: "organization",
      },
      {
        id: "personal-google",
        name: "Personal Google",
        kind: "api_key",
        purpose: "google",
        usage_scope: "personal",
      },
      {
        id: "org-openai",
        name: "Team OpenAI",
        kind: "api_key",
        purpose: "openai",
        usage_scope: "organization",
      },
    ],
    kinds: [],
    isLoading: false,
    create: { mutateAsync: vi.fn(), isPending: false },
  });
});

function mount(
  config: Record<string, unknown> = { provider: "google", model: "image-one" },
  options: {
    nodeType?: MediaGenerationNode;
    disabled?: boolean;
    errors?: ReadonlyMap<string, string>;
  } = {},
) {
  const onChange = vi.fn();
  const view = render(
    <MediaGenerationFields
      nodeType={options.nodeType ?? "image.generate"}
      idPrefix="media-node"
      config={config}
      onChange={onChange}
      disabled={options.disabled}
      errors={options.errors ?? new Map()}
    >
      {(allowed) => <span data-testid="reference-state">{String(allowed)}</span>}
    </MediaGenerationFields>,
  );
  return { ...view, onChange };
}

async function pick(name: string, option: string | RegExp) {
  await userEvent.click(screen.getByRole("combobox", { name }));
  await userEvent.click(screen.getByRole("option", { name: option }));
}

describe("workflow media generation settings", () => {
  it("uses explicit selections and the server's image defaults without silently writing config", () => {
    const { onChange } = mount();
    expect(screen.getByRole("combobox", { name: "Size" })).toHaveTextContent("1K");
    expect(screen.getByRole("combobox", { name: "Aspect ratio" })).toHaveTextContent("1:1");
    expect(screen.queryByRole("combobox", { name: "Quality" })).toBeNull();
    expect(screen.getByTestId("reference-state")).toHaveTextContent("true");
    expect(screen.getByText("Catalog pricing checked on 2026-11-16.")).toBeVisible();
    expect(onChange).not.toHaveBeenCalled();
    expect(videoCatalog).not.toHaveBeenCalled();
  });

  it("offers only workflow-enabled models and providers", async () => {
    mount();
    await userEvent.click(screen.getByRole("combobox", { name: "Model" }));
    expect(screen.getByRole("option", { name: /^Image One/ })).toBeVisible();
    expect(screen.queryByRole("option", { name: /Legacy image|No workflow/ })).toBeNull();
    await userEvent.keyboard("{Escape}");
    await userEvent.click(screen.getByRole("combobox", { name: "Provider" }));
    expect(screen.queryByRole("option", { name: "Agent-only provider" })).toBeNull();
  });

  it("clears the provider key and old model settings when changing provider", async () => {
    const { onChange } = mount({
      provider: "google",
      model: "image-one",
      secret_id: "org-google",
      size: "2K",
      aspect_ratio: "16:9",
      audio: true,
      filename: "keep.png",
      max_cost_usd: 2,
    });
    await pick("Provider", "OpenAI");
    expect(onChange).toHaveBeenCalledWith({
      provider: "openai",
      model: "text-image",
      quality: "low",
      size: "1024x1024",
      background: "opaque",
      output_format: "png",
      filename: "keep.png",
      max_cost_usd: 2,
    });
  });

  it("keeps the same provider's key but replaces model-specific options", async () => {
    const { onChange } = mount({
      provider: "google",
      model: "image-one",
      secret_id: "org-google",
      quality: "high",
    });
    await pick("Model", /^Image Two/);
    expect(onChange).toHaveBeenCalledWith({
      provider: "google",
      model: "image-two",
      secret_id: "org-google",
      size: "2K",
      aspect_ratio: "1:1",
    });
  });

  it("updates a catalog option and passes only an eligible key id to the graph", async () => {
    const { onChange } = mount();
    await pick("Size", "2K");
    expect(onChange).toHaveBeenLastCalledWith({
      provider: "google",
      model: "image-one",
      size: "2K",
    });
    await userEvent.click(screen.getByRole("combobox", { name: "Google API key" }));
    expect(screen.queryByRole("option", { name: /Personal Google|Team OpenAI/ })).toBeNull();
    await userEvent.click(screen.getByRole("option", { name: /Team Google/ }));
    expect(onChange).toHaveBeenLastCalledWith({
      provider: "google",
      model: "image-one",
      secret_id: "org-google",
    });
    callbacks.secret!(null);
    expect(onChange).toHaveBeenLastCalledWith({ provider: "google", model: "image-one" });
  });

  it("shows text-only settings, saved values and field refusals", () => {
    mount(
      { provider: "openai", model: "text-image", quality: "high", size: null },
      {
        errors: new Map([
          ["quality", "Unsupported quality"],
          ["secret_id", "Key is required"],
        ]),
      },
    );
    expect(screen.getByRole("combobox", { name: "Quality" })).toHaveTextContent("high");
    expect(screen.getByRole("combobox", { name: "Size" })).toHaveTextContent("1024x1024");
    expect(screen.getByRole("combobox", { name: "Background" })).toHaveTextContent("opaque");
    expect(screen.getByRole("combobox", { name: "File format" })).toHaveTextContent("png");
    expect(screen.getByText("Unsupported quality")).toBeVisible();
    expect(screen.getByText("Key is required")).toBeVisible();
    expect(screen.getByTestId("reference-state")).toHaveTextContent("false");
  });

  it("does not pretend an unconfigured node has a provider or model", () => {
    const { onChange } = mount({ provider: 12, model: null, secret_id: 34 });
    expect(screen.getByRole("combobox", { name: "Provider" })).toHaveTextContent(
      "Choose a provider",
    );
    expect(screen.getByRole("combobox", { name: "Model" })).toBeDisabled();
    expect(screen.getByRole("combobox", { name: "Provider API key" })).toBeDisabled();
    expect(onChange).not.toHaveBeenCalled();
  });

  it("retains an unavailable saved model and refuses a stale catalog choice", () => {
    const { onChange } = mount({ provider: "removed", model: "missing", secret_id: "old-key" });
    expect(
      screen.getByText("The saved provider removed is unavailable for this step."),
    ).toBeVisible();
    expect(
      screen.getByText(
        "The saved model missing is unavailable. Choose a supported model before running.",
      ),
    ).toBeVisible();
    expect(screen.getByText("old-key")).toBeVisible();
    callbacks.offering!({ provider: "removed", model: "missing" });
    expect(onChange).not.toHaveBeenCalled();
  });

  it.each(["loading", "error", "empty"])(
    "explains an %s catalog without changing the stored selection",
    (state) => {
      imageCatalog.mockReturnValue({
        providers: [],
        isLoading: state === "loading",
        isError: state === "error",
      });
      const { onChange } = mount();
      expect(
        screen.getByText(
          state === "loading"
            ? "Loading supported models…"
            : state === "error"
              ? "The model catalog could not be loaded. Reopen this step to try again."
              : "No models are currently available for this workflow step.",
        ),
      ).toBeVisible();
      expect(screen.getByTestId("reference-state")).toHaveTextContent(
        state === "empty" ? "false" : "null",
      );
      expect(onChange).not.toHaveBeenCalled();
    },
  );

  it("ignores late picker callbacks after the form becomes read-only", () => {
    const { onChange } = mount(undefined, { disabled: true });
    expect(screen.getByRole("combobox", { name: "Size" })).toBeDisabled();
    callbacks.offering!({ provider: "openai", model: "text-image" });
    callbacks.secret!("org-google");
    expect(onChange).not.toHaveBeenCalled();
  });

  it("uses the video catalog's duration and explicit sound default", async () => {
    const { onChange } = mount({ provider: "xai", model: "clip" }, { nodeType: "video.generate" });
    expect(imageCatalog).not.toHaveBeenCalled();
    const duration = screen.getByRole("spinbutton", { name: "Duration (seconds)" });
    expect(duration).toHaveValue(5);
    expect(duration).toHaveAttribute("min", "2");
    expect(duration).toHaveAttribute("max", "12");
    expect(screen.getByRole("combobox", { name: "Sound" })).toHaveTextContent("Without sound");
    await pick("Sound", "Include sound");
    expect(onChange).toHaveBeenLastCalledWith({ provider: "xai", model: "clip", audio: true });
    fireEvent.change(duration, { target: { value: "8" } });
    expect(onChange).toHaveBeenLastCalledWith({ provider: "xai", model: "clip", seconds: 8 });
    fireEvent.change(duration, { target: { value: "" } });
    expect(onChange).toHaveBeenLastCalledWith({ provider: "xai", model: "clip" });
    expect(screen.getByText("Choose a duration from 2 to 12 seconds.")).toBeVisible();
  });

  it("shows a saved video duration and can turn optional sound off", async () => {
    const { onChange } = mount(
      { provider: "xai", model: "clip", seconds: 9, audio: true },
      { nodeType: "video.generate" },
    );
    expect(screen.getByRole("spinbutton", { name: "Duration (seconds)" })).toHaveValue(9);
    await pick("Sound", "Without sound");
    expect(onChange).toHaveBeenLastCalledWith({
      provider: "xai",
      model: "clip",
      seconds: 9,
      audio: false,
    });
  });

  it("does not offer controls the video model decides itself", () => {
    mount({ provider: "xai", model: "automatic" }, { nodeType: "video.generate" });
    expect(screen.queryByRole("spinbutton")).toBeNull();
    expect(screen.queryByRole("combobox", { name: "Sound" })).toBeNull();
    expect(
      screen.getByText("This model chooses the duration, from 3 to 10 seconds."),
    ).toBeVisible();
    expect(screen.getByText("This model always includes sound.")).toBeVisible();
  });

  it("explains a silent video model", () => {
    mount({ provider: "xai", model: "silent" }, { nodeType: "video.generate" });
    expect(screen.getByText("This model produces video without sound.")).toBeVisible();
  });
});
