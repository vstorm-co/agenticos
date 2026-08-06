import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { IngestionSettings } from "./ingestion-settings";
import { apiClient } from "@/lib/api-client";
import { DEFAULT_INGESTION_CONFIG } from "@/lib/ingestion-config";
import type { IngestionConfig } from "@/types";

vi.mock("@/lib/api-client", () => ({
  apiClient: { get: vi.fn(), post: vi.fn(), patch: vi.fn(), delete: vi.fn() },
}));
vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));

function wrapper({ children }: { children: ReactNode }) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

/**
 * Render the form over a configuration, and hand back what it tried to change.
 *
 * jsdom cannot open a Radix select, so nothing here drives one - the selects are
 * exercised end to end. What is asserted is everything the form decides on its
 * own: which controls exist for a given parser, how an unset value reads, and
 * what leaves through `onChange`.
 */
function show(value: Partial<IngestionConfig> = {}) {
  const onChange = vi.fn<(next: IngestionConfig) => void>();
  render(
    <IngestionSettings
      idPrefix="test"
      value={{ ...DEFAULT_INGESTION_CONFIG, ...value }}
      onChange={onChange}
    />,
    { wrapper },
  );
  return onChange;
}

describe("IngestionSettings", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    // Everything this form reads is a list, except the caller's own permissions
    // - which the model field asks for, because whether it may offer to create
    // a model profile is `connections:manage`. A list-shaped answer there is not
    // "no permissions", it is a `TypeError` in `usePermissions`.
    vi.mocked(apiClient.get).mockImplementation(async (path: string) =>
      path === "/me/permissions"
        ? { organization_id: "org-1", role: "member", is_app_admin: false, permissions: [] }
        : { items: [], total: 0 },
    );
  });

  it("names every control it renders", () => {
    // Every label carries an `htmlFor`, which is what makes each of these
    // resolve. A form of unlabelled boxes is unusable with a screen reader and
    // untestable without test ids.
    show();

    expect(screen.getByLabelText("PDF parser")).toBeInTheDocument();
    expect(screen.getByLabelText("Read scanned pages")).toBeInTheDocument();
    expect(screen.getByLabelText("Chunk size")).toBeInTheDocument();
    expect(screen.getByLabelText("Overlap")).toBeInTheDocument();
    expect(screen.getByLabelText("Strategy")).toBeInTheDocument();
    expect(screen.getByLabelText("Describe images")).toBeInTheDocument();
  });

  it("hides the settings a parser ignores", () => {
    // LlamaParse's ladder means nothing to PyMuPDF and LiteParse's OCR language
    // means nothing to either of the others. A control that changes nothing is
    // worse than an absent one.
    show();

    expect(screen.queryByLabelText("LlamaParse tier")).not.toBeInTheDocument();
    expect(screen.queryByLabelText("OCR language")).not.toBeInTheDocument();
    expect(screen.queryByLabelText("Parse timeout (seconds)")).not.toBeInTheDocument();
  });

  it("offers a tier to the parser that has one", () => {
    show({ pdf_parser: "llamaparse" });

    expect(screen.getByLabelText("LlamaParse tier")).toBeInTheDocument();
  });

  it("offers OCR language and a timeout to the parser that reads them", () => {
    show({ pdf_parser: "liteparse" });

    expect(screen.getByLabelText("OCR language")).toBeInTheDocument();
    expect(screen.getByLabelText("Parse timeout (seconds)")).toBeInTheDocument();
  });

  it("keeps the image settings out of the way until they are asked for", () => {
    show();

    expect(screen.queryByLabelText("Prompt")).not.toBeInTheDocument();
    expect(screen.queryByLabelText("Temperature")).not.toBeInTheDocument();
    expect(screen.queryByLabelText("Reasoning")).not.toBeInTheDocument();
  });

  it("shows the image settings once they are switched on", () => {
    show({ describe_images: true });

    expect(screen.getByLabelText("Prompt")).toBeInTheDocument();
    expect(screen.getByLabelText("Temperature")).toBeInTheDocument();
    expect(screen.getByLabelText("Reasoning")).toBeInTheDocument();
  });

  it("shows an untouched temperature as unset rather than as a number", () => {
    // The reason this form exists in this shape: a slider resting at 1.00 and a
    // slider somebody moved to 1.00 mean different things on the wire, and only
    // the readout can tell them apart.
    show({ describe_images: true });

    expect(screen.getByText("Provider default")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Use provider default" })).not.toBeInTheDocument();
  });

  it("offers the way back to unset once, and only once, a temperature is set", () => {
    show({
      describe_images: true,
      image_description: { ...DEFAULT_INGESTION_CONFIG.image_description, temperature: 0.4 },
    });

    expect(screen.getByRole("button", { name: "Use provider default" })).toBeInTheDocument();
    expect(screen.getByText("0.40")).toBeInTheDocument();
  });

  it("puts a temperature back to null rather than to zero", async () => {
    // `undefined` would drop the key from an object the API requires whole, and
    // `0` is a value reasoning models reject. Neither is what the button means.
    const onChange = show({
      describe_images: true,
      image_description: { ...DEFAULT_INGESTION_CONFIG.image_description, temperature: 0.4 },
    });

    await userEvent.click(screen.getByRole("button", { name: "Use provider default" }));

    expect(onChange).toHaveBeenCalledWith(
      expect.objectContaining({
        image_description: expect.objectContaining({ temperature: null }),
      }),
    );
  });

  it("puts an edited prompt back to the standard one", async () => {
    // The reset doubles as the marker that the prompt was edited at all: the
    // alternative to a button is retyping four sentences nobody has kept.
    const onChange = show({
      describe_images: true,
      image_description: { ...DEFAULT_INGESTION_CONFIG.image_description, prompt: "Read tables." },
    });

    await userEvent.click(screen.getByRole("button", { name: "Use the standard prompt" }));

    expect(onChange).toHaveBeenCalledWith(
      expect.objectContaining({
        image_description: expect.objectContaining({
          prompt: DEFAULT_INGESTION_CONFIG.image_description.prompt,
        }),
      }),
    );
  });

  it("offers no way back from a prompt nobody changed", () => {
    show({ describe_images: true });

    expect(
      screen.queryByRole("button", { name: "Use the standard prompt" }),
    ).not.toBeInTheDocument();
  });

  it("reports an emptied chunk size as nothing typed, not as zero", async () => {
    const onChange = show();

    await userEvent.clear(screen.getByLabelText("Chunk size"));

    const [next] = onChange.mock.calls.at(-1) ?? [];
    expect(next?.chunk_size).toBeNaN();
  });

  it("says what the server refused, on the control it refused it about", async () => {
    render(
      <IngestionSettings
        idPrefix="test"
        value={DEFAULT_INGESTION_CONFIG}
        onChange={vi.fn()}
        errors={{ chunk_overlap: "Must be smaller than the chunk size of 512." }}
      />,
      { wrapper },
    );

    const overlap = screen.getByLabelText("Overlap");
    expect(overlap).toHaveAttribute("aria-invalid", "true");
    expect(overlap).toHaveAccessibleDescription("Must be smaller than the chunk size of 512.");
  });

  it("shows a refusal about the object as a whole without blaming a field", () => {
    // The overlap rule arrives from the server attributed to `ingestion_config`,
    // because it is about two fields at once. Pinning it to either would mark
    // the one nobody edited as wrong.
    render(
      <IngestionSettings
        idPrefix="test"
        value={DEFAULT_INGESTION_CONFIG}
        onChange={vi.fn()}
        errors={{ ingestion_config: "chunk_overlap (600) must be smaller than chunk_size (512)" }}
      />,
      { wrapper },
    );

    expect(
      screen.getByText("chunk_overlap (600) must be smaller than chunk_size (512)"),
    ).toBeInTheDocument();
    expect(screen.getByLabelText("Overlap")).not.toHaveAttribute("aria-invalid", "true");
  });
});
