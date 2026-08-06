import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { CreateKBDialog } from "./create-kb-dialog";
import { apiClient } from "@/lib/api-client";

/**
 * The Embeddings section of Create knowledge base, as somebody reading it sees it.
 *
 * Both selects here choose something billed to an OpenRouter key, and both used
 * to say so in bare text: "Deployment key", "OpenRouter", `text-embedding-3-large`.
 * The rest of the product draws that choice with the service's own mark, three
 * clicks away in the Builder. `create-kb-dialog.test.tsx` covers what the form
 * posts; this covers what it shows.
 */

vi.mock("@/lib/api-client", () => ({
  apiClient: { get: vi.fn(), post: vi.fn(), patch: vi.fn(), delete: vi.fn() },
}));
vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));

const SECRETS = {
  items: [
    { id: "s-1", name: "OpenRouter prod", hint: "3123", purpose: "openrouter", kind: "api_key" },
    // A key for something else entirely: it must not be offered as one that can
    // pay for embeddings, and its mark must not appear in this select either.
    { id: "s-2", name: "Tavily", hint: "9999", purpose: "tavily", kind: "api_key" },
  ],
  total: 2,
};

const EMBEDDING_MODELS = {
  default: "text-embedding-3-large",
  models: [
    { model: "text-embedding-3-large", dim: 3072 },
    { model: "text-embedding-3-small", dim: 1536 },
  ],
};

function wrapper({ children }: { children: ReactNode }) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

/** The brand mark actually drawn, by the name lobehub titles its SVG with. */
function markIn(element: HTMLElement): string | null {
  return element.querySelector("svg > title")?.textContent ?? null;
}

/** Open the disclosure the embedding model and its key live behind. */
async function openEmbeddings() {
  await userEvent.click(screen.getByText("Embeddings"));
}

/** Open the disclosure the parser options and the images model live behind. */
async function openParsing() {
  await userEvent.click(screen.getByText("How documents are parsed"));
}

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(apiClient.get).mockImplementation(async (path: string) => {
    if (path === "/secrets") return SECRETS;
    if (path === "/rag/embedding-models") return EMBEDDING_MODELS;
    // The images section reads the caller's permissions, the provider catalog
    // and what each provider publishes. Answering a list shape at
    // `/me/permissions` is not "no permissions", it is a `TypeError`.
    if (path === "/me/permissions")
      return {
        organization_id: "org-1",
        role: "builder",
        is_app_admin: false,
        permissions: [
          { permission: "connections:manage", scope: "all" },
          { permission: "secrets:edit", scope: "all" },
        ],
      };
    if (path === "/providers/catalog")
      return {
        items: [
          {
            id: "openai",
            name: "OpenAI",
            secret_kind: "api_key",
            supports_base_url: false,
            keyless: false,
          },
        ],
        total: 1,
      };
    if (path === "/secrets/purposes")
      return {
        items: [
          {
            id: "openai",
            label: "OpenAI",
            category: "model_provider",
            kind: "api_key",
            help_url: null,
            description: "OpenAI keys",
          },
        ],
        total: 1,
      };
    if (path === "/providers/openai/models") return { items: [], total: 0, source: null };
    return { items: [], total: 0 };
  });
  render(<CreateKBDialog open onOpenChange={vi.fn()} />, { wrapper });
});

describe("the embedding key picker", () => {
  it("draws the mark for every key it offers, and its masked tail", async () => {
    await openEmbeddings();
    await userEvent.click(screen.getByLabelText("Key"));

    const key = await screen.findByRole("option", { name: /OpenRouter prod/ });
    expect(markIn(key)).toBe("OpenRouter");
    expect(key).toHaveTextContent("····3123");
  });

  it("marks the deployment's own key too, which is an OpenRouter key as well", async () => {
    // `EmbeddingService` sends every embedding request to openrouter.ai, on the
    // deployment's key when a collection names none - so the two rows are the
    // same service and reading as two different things was the bug.
    await openEmbeddings();
    await userEvent.click(screen.getByLabelText("Key"));

    expect(markIn(await screen.findByRole("option", { name: "Deployment key" }))).toBe(
      "OpenRouter",
    );
  });

  it("offers no key that cannot pay for embeddings", async () => {
    await openEmbeddings();
    await userEvent.click(screen.getByLabelText("Key"));

    expect(screen.queryByRole("option", { name: /Tavily/ })).toBeNull();
  });

  it("shows the selected key's mark on the closed trigger", async () => {
    await openEmbeddings();

    expect(markIn(screen.getByLabelText("Key"))).toBe("OpenRouter");
  });
});

describe("the embedding model picker", () => {
  it("names the model the collection would be created with", async () => {
    // The one choice in this dialog that cannot be revisited - the vector column
    // is created at the model's width - and the trigger used to sit on its
    // placeholder for as long as the dialog was open. Mounting a controlled
    // Radix select before its options exist writes the value onto a hidden
    // native `<select>` with no matching `<option>`, reads `""` back out of the
    // change event, and hands that to `onValueChange`, which is `setState`.
    await openEmbeddings();

    expect(await screen.findByLabelText("Model")).toHaveTextContent("text-embedding-3-large");
    expect(screen.queryByText("Loading models…")).toBeNull();
  });

  it("says the list is still loading rather than offering an empty picker", () => {
    // Asserted before the query resolves, which is the state the placeholder is
    // for: no select at all, because one whose value arrives after its options
    // is the bug above.
    expect(screen.getByText("Loading models…")).toBeInTheDocument();
    expect(screen.queryByLabelText("Model")).toBeNull();
  });

  it("draws the mark of the key that pays, beside every model id", async () => {
    await openEmbeddings();
    await userEvent.click(screen.getByLabelText("Model"));

    expect(markIn(await screen.findByRole("option", { name: /text-embedding-3-small/ }))).toBe(
      "OpenRouter",
    );
  });

  it("says which model an untouched deployment would use, in the list", async () => {
    await openEmbeddings();
    await userEvent.click(screen.getByLabelText("Model"));

    const preselected = await screen.findByRole("option", { name: /text-embedding-3-large/ });
    expect(preselected).toHaveTextContent("deployment default");
  });
});

describe("the two keys this dialog can store", () => {
  /**
   * On a fresh deployment both offers appear at once - an embedding key in the
   * Embeddings section and a model-provider key in the describing-model form,
   * four inches apart, writing different secrets under different purposes. Both
   * were labelled "Add a key", so a screen reader heard the same button twice
   * and a test could only tell them apart by DOM position.
   */

  it("names each of them, so neither of them is just 'a key'", async () => {
    await openEmbeddings();
    await openParsing();
    await userEvent.click(screen.getByLabelText("Describe images"));
    await userEvent.click(await screen.findByLabelText("Provider"));
    await userEvent.click(screen.getByRole("option", { name: /OpenAI/ }));

    // Two offers, and the accessible name is what tells them apart - not the
    // section each happens to sit in.
    expect(
      screen.getByRole("button", { name: "Add a key: OpenRouter (embeddings)" }),
    ).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Add a key: OpenAI" })).toBeInTheDocument();
  });
});
