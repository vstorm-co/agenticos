import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
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
  default: "text-embedding-3-large",
  default_provider: "openrouter",
  providers: [
    {
      provider: "openrouter",
      name: "OpenRouter",
      deployment_key: true,
      models: [
        { model: "text-embedding-3-small", dim: 1536 },
        { model: "text-embedding-3-large", dim: 3072 },
      ],
    },
    {
      provider: "openai",
      name: "OpenAI",
      deployment_key: false,
      models: [{ model: "text-embedding-3-small", dim: 1536 }],
    },
    // Serves the same model at another width, which is another space: offering
    // it would offer a move the server refuses and the vectors could not survive.
    {
      provider: "elsewhere",
      name: "Elsewhere",
      deployment_key: false,
      models: [{ model: "text-embedding-3-small", dim: 3072 }],
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
} as KnowledgeBase;

function wrapper({ children }: { children: ReactNode }) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

const save = vi.fn();

function show(kb: KnowledgeBase = KB) {
  render(<EmbeddingDialog open onOpenChange={vi.fn()} kb={kb} onSave={save} />, { wrapper });
}

beforeEach(() => {
  vi.clearAllMocks();
  save.mockResolvedValue(undefined);
  vi.mocked(apiClient.get).mockImplementation(async (path: string) => {
    if (path === "/rag/embedding-models") return MODELS;
    if (path === "/secrets")
      return {
        items: [
          { id: "s-1", name: "OpenAI prod", hint: "7777", purpose: "openai", kind: "api_key" },
        ],
        total: 1,
      };
    if (path === "/me/permissions")
      return {
        organization_id: "org-1",
        role: "builder",
        is_app_admin: false,
        permissions: [],
      };
    return { items: [], total: 0 };
  });
});

describe("what this dialog will and will not change", () => {
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

  it("saves the provider and falls back to the deployment's key by its own word", async () => {
    // A null id means "leave the key alone" on a partial update, so going back to
    // the deployment's key has to be sayable rather than implied by absence.
    show();
    await userEvent.click(await screen.findByLabelText("Embedding provider"));
    await userEvent.click(await screen.findByRole("option", { name: "OpenAI" }));
    await userEvent.click(screen.getByRole("button", { name: "Save" }));

    await waitFor(() => expect(save).toHaveBeenCalled());
    expect(save.mock.calls[0]?.[0]).toEqual({
      embedding_provider: "openai",
      clear_embedding_secret: true,
    });
  });

  it("sends the key chosen for the new provider", async () => {
    show();
    await userEvent.click(await screen.findByLabelText("Embedding provider"));
    await userEvent.click(await screen.findByRole("option", { name: "OpenAI" }));
    await userEvent.click(screen.getByLabelText("Key"));
    await userEvent.click(await screen.findByRole("option", { name: /OpenAI prod/ }));
    await userEvent.click(screen.getByRole("button", { name: "Save" }));

    await waitFor(() => expect(save).toHaveBeenCalled());
    expect(save.mock.calls[0]?.[0]).toEqual({
      embedding_provider: "openai",
      embedding_secret_id: "s-1",
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
    await userEvent.click(screen.getByRole("button", { name: "Save" }));

    expect(await screen.findByText(/does not serve it at 1536/)).toBeInTheDocument();
  });
});
