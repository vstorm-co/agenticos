import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { EmbeddingDialog } from "./embedding-dialog";
import { apiClient } from "@/lib/api-client";
import { ApiError } from "@/lib/api-error";
import type { KnowledgeBase } from "@/types";

/**
 * Moving an existing collection's embeddings to another provider.
 *
 * The model is the thing that cannot move - the vector column was created at its
 * width and every stored vector is in its space - and before this the provider
 * could not either: every request went to openrouter.ai, hardcoded, so an
 * organization holding an OpenAI key had no way to use it and a key rotated onto
 * another account meant re-ingesting the collection.
 *
 * So what this asserts is the boundary between the two: the model is drawn and
 * not offered, and only providers that serve *this* model at *this* width are.
 */

vi.mock("@/lib/api-client", () => ({
  apiClient: { get: vi.fn(), post: vi.fn(), patch: vi.fn(), delete: vi.fn() },
}));
vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));

const MODELS = {
  providers: [
    {
      provider: "openrouter",
      name: "OpenRouter",
      keyless: false,
      any_model: false,
      models: [
        { model: "text-embedding-3-small", dim: 1536 },
        { model: "text-embedding-3-large", dim: 3072 },
      ],
    },
    {
      provider: "openai",
      name: "OpenAI",
      keyless: false,
      any_model: false,
      models: [{ model: "text-embedding-3-small", dim: 1536 }],
    },
    // A keyless endpoint on the deployment's own network that happens to serve
    // this model at this width: a move the server accepts with no key.
    {
      provider: "ollama",
      name: "Ollama",
      keyless: true,
      any_model: false,
      models: [{ model: "text-embedding-3-small", dim: 1536 }],
    },
    // Serves the same model at another width, which is another space: offering
    // it would offer a move the server refuses and the vectors could not survive.
    {
      provider: "elsewhere",
      name: "Elsewhere",
      keyless: false,
      any_model: false,
      models: [{ model: "text-embedding-3-small", dim: 3072 }],
    },
    // A gateway that serves any model: it qualifies on the stored width alone.
    {
      provider: "openai_compatible",
      name: "Custom (OpenAI-compatible)",
      keyless: false,
      any_model: true,
      models: [],
    },
  ],
};

const KB = {
  id: "kb-1",
  name: "Handbook",
  embedding_model: "text-embedding-3-small",
  embedding_dim: 1536,
  embedding_provider: "openrouter",
  embedding_secret_id: null,
  embedding_endpoint_id: null,
} as KnowledgeBase;

function wrapper({ children }: { children: ReactNode }) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

let mayManage = false;
let estimateMode: "ok" | "pending" | "error" | "opaque" = "ok";
// What `GET /rag/embedding-models/openrouter?base_url=` answers, per test.
let endpointModels: {
  provider: string;
  models: { model: string; dim: number }[];
  source: string;
} | null = null;
const save = vi.fn();

const PASSED = {
  passed: true,
  outcome: "passed",
  dim: null,
  calls: 3,
  knowledge_bases: [
    { knowledge_base_id: "kb-1", name: "Handbook", outcome: "passed", min_cosine: 1, calls: 3 },
  ],
  probe_token: "tok",
  expires_at: "2026-11-25T12:10:00Z",
};

/** Test the move, then save it: a move cannot be saved until a test of it has passed. */
async function testThenSave() {
  await userEvent.click(screen.getByRole("button", { name: "Test" }));
  await waitFor(() => expect(screen.getByRole("button", { name: "Save" })).toBeEnabled());
  await userEvent.click(screen.getByRole("button", { name: "Save" }));
}

function show(kb: KnowledgeBase = KB) {
  render(<EmbeddingDialog open onOpenChange={vi.fn()} kb={kb} onSave={save} />, { wrapper });
}

beforeEach(() => {
  vi.clearAllMocks();
  mayManage = false;
  estimateMode = "ok";
  endpointModels = null;
  save.mockResolvedValue(undefined);
  vi.mocked(apiClient.post).mockResolvedValue(PASSED);
  vi.mocked(apiClient.get).mockImplementation(async (path: string) => {
    if (path === "/rag/embedding-models") return MODELS;
    if (path.startsWith("/rag/embedding-models/openrouter?base_url=") && endpointModels !== null)
      return endpointModels;
    if (path === "/service-connections")
      return {
        items: [
          {
            id: "ls-1",
            organization_id: "org-1",
            kind: "embedding",
            provider: "ollama",
            name: "GPU box",
            base_url: "http://ollama:11434/v1",
            is_active: true,
            created_at: "2026-09-01T00:00:00Z",
            updated_at: null,
          },
          {
            id: "conn-1",
            organization_id: "org-1",
            kind: "embedding",
            provider: "openai_compatible",
            name: "Corp gateway",
            base_url: "https://gw.example/v1",
            is_active: true,
            secret_id: "s-9",
            requires_key: true,
            created_at: "2026-09-01T00:00:00Z",
            updated_at: null,
          },
        ],
        total: 2,
      };
    if (path === "/secrets")
      return {
        items: [
          { id: "s-1", name: "OpenAI prod", hint: "7777", purpose: "openai", kind: "api_key" },
        ],
        total: 1,
      };
    if (path === "/kb/kb-1/embedding-probe/estimate") {
      if (estimateMode === "pending") return new Promise(() => {});
      if (estimateMode === "error") throw new Error("estimate failed");
      // Not an Error at all: nothing to quote, so the dialog falls back to its own words.
      if (estimateMode === "opaque") throw "unreadable";
      return { calls: 3, max_calls: 6, knowledge_bases: 1 };
    }
    if (path === "/me/permissions")
      return {
        organization_id: "org-1",
        role: "builder",
        is_app_admin: false,
        permissions: mayManage ? [{ permission: "connections:manage", scope: "all" }] : [],
      };
    return { items: [], total: 0 };
  });
});

describe("what this dialog will and will not change", () => {
  it("freezes the provider draft until the write settles", async () => {
    let reject!: (error: Error) => void;
    save.mockReturnValueOnce(
      new Promise<never>((_resolve, fail) => {
        reject = fail;
      }),
    );
    show();
    await userEvent.click(await screen.findByLabelText("Embedding provider"));
    await userEvent.click(await screen.findByRole("option", { name: "OpenAI" }));
    await testThenSave();
    expect(screen.getByLabelText("Embedding provider")).toBeDisabled();
    expect(screen.getByLabelText("Key")).toBeDisabled();
    await act(async () => reject(new Error("Refused")));
    await waitFor(() => expect(screen.getByLabelText("Embedding provider")).toBeEnabled());
    expect(screen.getByLabelText("Embedding provider")).toHaveTextContent("OpenAI");
  });

  it("states the model rather than offering it", async () => {
    show();

    expect(await screen.findByText("text-embedding-3-small")).toBeInTheDocument();
    expect(screen.queryByLabelText("Model")).toBeNull();
  });

  it("says the index survives the move, because that is the question", async () => {
    show();

    expect(await screen.findByText(/nothing already indexed changes/)).toBeInTheDocument();
  });

  it("offers only providers that serve this model at this width", async () => {
    show();
    await userEvent.click(await screen.findByLabelText("Embedding provider"));

    expect(await screen.findByRole("option", { name: "OpenAI" })).toBeVisible();
    expect(screen.getByRole("option", { name: "OpenRouter" })).toBeVisible();
    expect(screen.queryByRole("option", { name: "Elsewhere" })).toBeNull();
  });

  it("saves the provider alone when no key was chosen, and never asks to clear one", async () => {
    // A null id means "leave the key alone" on a partial update. There is no
    // deployment-wide key to go back to, so "clear the key" is not a thing this
    // dialog can say - the server keeps whatever key the row holds.
    show();
    await userEvent.click(await screen.findByLabelText("Embedding provider"));
    await userEvent.click(await screen.findByRole("option", { name: "OpenAI" }));
    await testThenSave();

    await waitFor(() => expect(save).toHaveBeenCalled());
    expect(save.mock.calls[0]?.[0]).toEqual({ embedding_provider: "openai", probe_token: "tok" });
  });

  it("offers no deployment key, and reads as empty until one is chosen", async () => {
    show();
    await userEvent.click(await screen.findByLabelText("Embedding provider"));
    await userEvent.click(await screen.findByRole("option", { name: "OpenAI" }));

    expect(screen.getByLabelText("Key")).toHaveTextContent("Choose a key");
    await userEvent.click(screen.getByLabelText("Key"));
    expect(screen.queryByRole("option", { name: /Deployment key/ })).toBeNull();
  });

  it("moving to a keyless provider asks for a server, and sends it with no key", async () => {
    show();
    await userEvent.click(await screen.findByLabelText("Embedding provider"));
    await userEvent.click(await screen.findByRole("option", { name: "Ollama" }));

    expect(screen.queryByLabelText("Key")).toBeNull();
    expect(screen.getByText(/Ollama takes no key/)).toBeVisible();
    await userEvent.click(screen.getByLabelText("Server"));
    await userEvent.click(await screen.findByRole("option", { name: /GPU box/ }));
    await testThenSave();

    await waitFor(() => expect(save).toHaveBeenCalled());
    expect(save.mock.calls[0]?.[0]).toEqual({
      embedding_provider: "ollama",
      embedding_endpoint_id: "ls-1",
      probe_token: "tok",
    });
  });

  it("sends the key chosen for the new provider", async () => {
    show();
    await userEvent.click(await screen.findByLabelText("Embedding provider"));
    await userEvent.click(await screen.findByRole("option", { name: "OpenAI" }));
    await userEvent.click(screen.getByLabelText("Key"));
    await userEvent.click(await screen.findByRole("option", { name: /OpenAI prod/ }));
    await testThenSave();

    await waitFor(() => expect(save).toHaveBeenCalled());
    expect(save.mock.calls[0]?.[0]).toEqual({
      embedding_provider: "openai",
      embedding_secret_id: "s-1",
      probe_token: "tok",
    });
  });

  it("saves nothing while nothing has moved", async () => {
    show();
    await screen.findByLabelText("Embedding provider");

    expect(screen.getByRole("button", { name: "Save" })).toBeDisabled();
  });

  it("puts the server's refusal on screen rather than losing it", async () => {
    // The move the server refuses is a provider that cannot serve the model, and
    // the reason is not something a person should have to discover twice.
    save.mockRejectedValue(
      new ApiError(400, "OpenAI does not serve it at 1536 dimensions", {
        error: {
          code: "BAD_REQUEST",
          message: "OpenAI does not serve it at 1536 dimensions",
          details: {
            fields: [
              {
                field: "embedding_provider",
                message: "OpenAI does not serve it at 1536 dimensions",
              },
            ],
          },
        },
      }),
    );
    show();
    await userEvent.click(await screen.findByLabelText("Embedding provider"));
    await userEvent.click(await screen.findByRole("option", { name: "OpenAI" }));
    await testThenSave();

    expect(await screen.findByText(/does not serve it at 1536/)).toBeInTheDocument();
  });
});

it("prefills a regional endpoint and lets a connection manager restore the default", async () => {
  mayManage = true;
  show({
    ...KB,
    embedding_provider: "openrouter",
    embedding_secret_id: "openrouter-key",
    embedding_base_url: "https://eu.openrouter.ai/api/v1",
  });
  const endpoint = await screen.findByLabelText("Endpoint");
  expect(endpoint).toHaveValue("https://eu.openrouter.ai/api/v1");
  await waitFor(() => expect(endpoint).toBeEnabled());
  await userEvent.clear(endpoint);
  await testThenSave();
  await waitFor(() =>
    expect(save).toHaveBeenCalledWith(expect.objectContaining({ embedding_base_url: null })),
  );
});

it("says before saving that an endpoint does not serve the collection's model", async () => {
  // OpenRouter's EU endpoint has none of OpenAI's models, and the vectors cannot
  // move to another one - so the move is refused, and saying so on save was late.
  mayManage = true;
  endpointModels = {
    provider: "openrouter",
    models: [{ model: "mistralai/mistral-embed-2312", dim: 1024 }],
    source: "live",
  };
  show({ ...KB, embedding_secret_id: "openrouter-key" });
  await userEvent.type(await screen.findByLabelText("Endpoint"), "https://eu.openrouter.ai/api/v1");

  expect(
    await screen.findByText(/This endpoint does not serve text-embedding-3-small/),
  ).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Save" })).toBeDisabled();
});

it("holds Save until the endpoint has said whether it serves the model", async () => {
  // The warning above arrives after a debounce and a request; a Save pressed in
  // between would post the address the dialog is about to warn about.
  mayManage = true;
  let answer: (value: unknown) => void = () => {};
  vi.mocked(apiClient.get).mockImplementation(async (path: string) => {
    if (path === "/rag/embedding-models") return MODELS;
    if (path.startsWith("/rag/embedding-models/openrouter?base_url="))
      return new Promise((resolve) => {
        answer = resolve;
      });
    if (path === "/me/permissions")
      return {
        organization_id: "org-1",
        role: "builder",
        is_app_admin: false,
        permissions: [{ permission: "connections:manage", scope: "all" }],
      };
    return { items: [], total: 0 };
  });
  show({ ...KB, embedding_secret_id: "openrouter-key" });
  await userEvent.type(await screen.findByLabelText("Endpoint"), "https://eu.openrouter.ai/api/v1");

  expect(screen.getByRole("button", { name: "Save" })).toBeDisabled();
  await waitFor(() =>
    expect(
      vi
        .mocked(apiClient.get)
        .mock.calls.some(([path]) => String(path).startsWith("/rag/embedding-models/openrouter")),
    ).toBe(true),
  );
  expect(screen.getByRole("button", { name: "Save" })).toBeDisabled();

  answer({
    provider: "openrouter",
    models: [{ model: "text-embedding-3-small", dim: 1536 }],
    source: "live",
  });
  await waitFor(() => expect(screen.getByRole("button", { name: "Test" })).toBeEnabled());
});

describe("testing a move against the stored chunks", () => {
  const FAILED = {
    passed: false,
    outcome: "vectors_differ",
    dim: null,
    calls: 6,
    knowledge_bases: [
      {
        knowledge_base_id: "kb-1",
        name: "Handbook",
        outcome: "vectors_differ",
        min_cosine: 0.2,
        calls: 6,
      },
    ],
    probe_token: null,
    expires_at: null,
  };

  async function moveToOpenAI() {
    show();
    await userEvent.click(await screen.findByLabelText("Embedding provider"));
    await userEvent.click(await screen.findByRole("option", { name: "OpenAI" }));
  }

  it("lists the custom provider as a move target for a 1536-wide collection", async () => {
    show();
    await userEvent.click(await screen.findByLabelText("Embedding provider"));

    expect(
      await screen.findByRole("option", { name: /Custom \(OpenAI-compatible\)/ }),
    ).toBeVisible();
  });

  it("does not list the custom provider for a width the index cannot hold", async () => {
    show({ ...KB, embedding_dim: 4096 });
    await userEvent.click(await screen.findByLabelText("Embedding provider"));

    expect(screen.queryByRole("option", { name: /Custom/ })).toBeNull();
  });

  it("keeps Test disabled while the estimate is loading", async () => {
    estimateMode = "pending";
    await moveToOpenAI();

    const test = screen.getByRole("button", { name: "Test" });
    expect(test).toBeDisabled();
    await userEvent.click(test);
    expect(apiClient.post).not.toHaveBeenCalled();
  });

  it("says why the count is missing and keeps Test disabled when the estimate fails", async () => {
    estimateMode = "error";
    await moveToOpenAI();

    expect(await screen.findByText("estimate failed")).toBeVisible();
    expect(screen.getByRole("button", { name: "Test" })).toBeDisabled();
  });

  it("falls back to its own words when the failed estimate says nothing", async () => {
    estimateMode = "opaque";
    await moveToOpenAI();

    expect(await screen.findByText("Could not read how many probes the test makes.")).toBeVisible();
    expect(screen.getByRole("button", { name: "Test" })).toBeDisabled();
  });

  it("says a custom model is tested rather than fixed", async () => {
    show();
    expect(await screen.findByText(/Model, fixed by the vectors already stored/)).toBeVisible();
    await userEvent.click(await screen.findByLabelText("Embedding provider"));
    await userEvent.click(
      await screen.findByRole("option", { name: /Custom \(OpenAI-compatible\)/ }),
    );

    expect(screen.getByText(/tested against the stored chunks/)).toBeVisible();
  });

  it("offers no save without testing until a custom move has its server and model", async () => {
    show();
    await userEvent.click(await screen.findByLabelText("Embedding provider"));
    await userEvent.click(
      await screen.findByRole("option", { name: /Custom \(OpenAI-compatible\)/ }),
    );

    expect(screen.getByRole("button", { name: "Save without testing" })).toBeDisabled();
  });

  it("moves a collection with the tested token", async () => {
    await moveToOpenAI();
    expect(await screen.findByText("3 probes")).toBeVisible();
    expect(screen.getByRole("button", { name: "Save" })).toBeDisabled();

    await userEvent.click(screen.getByRole("button", { name: "Test" }));
    expect(await screen.findByText("1 knowledge base keeps its vectors")).toBeVisible();
    expect(apiClient.post).toHaveBeenCalledWith("/kb/kb-1/embedding-probe", {
      embedding_provider: "openai",
    });
    await userEvent.click(screen.getByRole("button", { name: "Save" }));

    await waitFor(() =>
      expect(save).toHaveBeenCalledWith({ embedding_provider: "openai", probe_token: "tok" }),
    );
  });

  it("keeps the draft and its passing test when the ingest poll refreshes the row", async () => {
    const { rerender } = render(
      <EmbeddingDialog open onOpenChange={vi.fn()} kb={KB} onSave={save} />,
      { wrapper },
    );
    await userEvent.click(await screen.findByLabelText("Embedding provider"));
    await userEvent.click(await screen.findByRole("option", { name: "OpenAI" }));
    await userEvent.click(await screen.findByRole("button", { name: "Test" }));
    await waitFor(() => expect(screen.getByRole("button", { name: "Save" })).toBeEnabled());

    // A poll answers with a new row object; only the counts moved.
    rerender(
      <EmbeddingDialog
        open
        onOpenChange={vi.fn()}
        kb={{ ...KB, document_count: KB.document_count + 1 }}
        onSave={save}
      />,
    );

    expect(screen.getByRole("button", { name: "Save" })).toBeEnabled();
    expect(screen.getByText("1 knowledge base keeps its vectors")).toBeVisible();
    // A passing test leaves nothing to override.
    expect(screen.queryByRole("button", { name: "Save without testing" })).toBeNull();
  });

  it("moves a collection unverified only after the confirmation", async () => {
    await moveToOpenAI();

    await userEvent.click(screen.getByRole("button", { name: "Save without testing" }));
    expect(save).not.toHaveBeenCalled();
    await userEvent.click(await screen.findByRole("button", { name: "Save anyway" }));

    await waitFor(() =>
      expect(save).toHaveBeenCalledWith({ embedding_provider: "openai", unverified: true }),
    );
  });

  it("names the failure cause and advises a new knowledge base", async () => {
    vi.mocked(apiClient.post).mockResolvedValue(FAILED);
    await moveToOpenAI();
    await userEvent.click(screen.getByRole("button", { name: "Test" }));

    expect(await screen.findByText(/Handbook:/)).toBeVisible();
    expect(screen.getByText("Create a new knowledge base for these settings.")).toBeVisible();
    expect(screen.getByRole("button", { name: "Save" })).toBeDisabled();
  });

  it("moves onto a custom endpoint with a typed model after a passing test", async () => {
    show();
    await userEvent.click(await screen.findByLabelText("Embedding provider"));
    await userEvent.click(
      await screen.findByRole("option", { name: /Custom \(OpenAI-compatible\)/ }),
    );
    // Prefilled with the model already stored: the same one is the common case.
    expect(screen.getByLabelText("Model")).toHaveValue("text-embedding-3-small");
    await userEvent.clear(screen.getByLabelText("Model"));
    await userEvent.click(screen.getByLabelText("Server"));
    await userEvent.click(await screen.findByRole("option", { name: /Corp gateway/ }));
    await userEvent.type(screen.getByLabelText("Model"), "corp-embed");
    await testThenSave();

    await waitFor(() =>
      expect(save).toHaveBeenCalledWith({
        embedding_provider: "openai_compatible",
        embedding_endpoint_id: "conn-1",
        embedding_model: "corp-embed",
        probe_token: "tok",
      }),
    );
  });

  it("still saves a catalog key change after a passing test", async () => {
    show({ ...KB, embedding_provider: "openai", embedding_secret_id: "s-0" });
    await userEvent.click(await screen.findByLabelText("Key"));
    await userEvent.click(await screen.findByRole("option", { name: /OpenAI prod/ }));
    await testThenSave();

    await waitFor(() =>
      expect(save).toHaveBeenCalledWith({
        embedding_provider: "openai",
        embedding_secret_id: "s-1",
        probe_token: "tok",
      }),
    );
  });
});
