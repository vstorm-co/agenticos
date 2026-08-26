import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { CreateKBDialog } from "./create-kb-dialog";
import { apiClient } from "@/lib/api-client";
import { ApiError } from "@/lib/api-error";
import { DEFAULT_INGESTION_CONFIG } from "@/lib/ingestion-config";

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

const create = () => screen.getByRole("button", { name: "Create" });

/** Open the disclosure the parser options live behind. */
async function openIngestion() {
  await userEvent.click(screen.getByText("How documents are parsed"));
}

/** The body of the one `POST /kb` the dialog made. */
function posted(): Record<string, unknown> {
  const call = vi.mocked(apiClient.post).mock.calls.at(-1);
  expect(call?.[0]).toBe("/kb");
  return call?.[1] as Record<string, unknown>;
}

describe("CreateKBDialog", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    // Every list this dialog reads is empty, except the one that is not a list:
    // `/rag/embedding-models` answers `{default, default_provider, providers}`,
    // and the two selects are built from it rather than tolerating whatever
    // arrives - the provider decides which models and which keys are on offer.
    vi.mocked(apiClient.get).mockImplementation(async (path: string) => {
      if (path === "/rag/embedding-models")
        return {
          default: "text-embedding-3-large",
          default_provider: "openrouter",
          providers: [
            {
              provider: "openrouter",
              name: "OpenRouter",
              deployment_key: true,
              models: [{ model: "text-embedding-3-large", dim: 3072 }],
            },
          ],
        };
      // Nor is `/me/permissions`, which the two key forms read: a list shape
      // there is a `TypeError` in `usePermissions`, not "no permissions".
      if (path === "/me/permissions")
        return { organization_id: "org-1", role: "member", is_app_admin: false, permissions: [] };
      // One key that can pay for reranking, so the picker has something to
      // choose beyond Off. Its purpose is what makes it a rerank key.
      if (path === "/secrets")
        return {
          items: [
            {
              id: "cohere-1",
              name: "Cohere key",
              hint: "4242",
              purpose: "cohere",
              kind: "api_key",
            },
          ],
          total: 1,
        };
      return { items: [], total: 0 };
    });
    vi.mocked(apiClient.post).mockResolvedValue({ id: "kb-1", name: "Handbook" });
    render(<CreateKBDialog open onOpenChange={vi.fn()} />, { wrapper });
  });

  it("sends no ingestion configuration for a collection nobody configured", async () => {
    // The one that matters. The API fills a *missing* object from the
    // deployment's own settings, which an operator may have set to something
    // other than the platform's - so posting the form's starting values would
    // quietly overrule them for every collection anyone ever made here.
    await userEvent.type(screen.getByLabelText("Name"), "Handbook");
    await userEvent.click(create());

    await waitFor(() => expect(apiClient.post).toHaveBeenCalled());
    expect(posted()).not.toHaveProperty("ingestion_config");
  });

  it("sends nothing even after the settings were opened and looked at", async () => {
    // Opening a disclosure is not a decision. This is the difference between
    // "shows the defaults" and "chose the defaults".
    await userEvent.type(screen.getByLabelText("Name"), "Handbook");
    await openIngestion();
    await userEvent.click(create());

    await waitFor(() => expect(apiClient.post).toHaveBeenCalled());
    expect(posted()).not.toHaveProperty("ingestion_config");
  });

  it("sends the whole configuration once one field is moved off it", async () => {
    // Update and create both replace it wholesale - there is no partial merge -
    // so a chosen chunk size has to arrive with the nine other fields it was
    // chosen alongside.
    await userEvent.type(screen.getByLabelText("Name"), "Handbook");
    await openIngestion();
    await userEvent.clear(screen.getByLabelText("Chunk size"));
    await userEvent.type(screen.getByLabelText("Chunk size"), "1024");
    await userEvent.click(create());

    await waitFor(() => expect(apiClient.post).toHaveBeenCalled());
    expect(posted().ingestion_config).toEqual({
      ...DEFAULT_INGESTION_CONFIG,
      chunk_size: 1024,
    });
  });

  it("refuses to send an overlap that does not fit inside a chunk", async () => {
    // The server refuses this with a 422 attributed to the object rather than to
    // a field. Answering it here puts it under the input that caused it, and
    // saves a round trip that would discard nothing but is still a round trip.
    await userEvent.type(screen.getByLabelText("Name"), "Handbook");
    await openIngestion();
    await userEvent.clear(screen.getByLabelText("Overlap"));
    await userEvent.type(screen.getByLabelText("Overlap"), "600");

    expect(create()).toBeDisabled();
    expect(screen.getByLabelText("Overlap")).toHaveAccessibleDescription(/smaller than/);
    expect(apiClient.post).not.toHaveBeenCalled();
  });

  it("puts a refused chunk size under the chunk size", async () => {
    // The server names `ingestion_config.chunk_size`; the input is called
    // `chunk_size`. Anything less specific than this ends up as a toast that
    // leaves nothing behind on the form still holding the value.
    vi.mocked(apiClient.post).mockRejectedValue(
      new ApiError(422, "chunk size", {
        error: {
          code: "VALIDATION_ERROR",
          message: "ingestion_config.chunk_size: Input should be less than or equal to 8192",
          details: {
            fields: [
              {
                field: "ingestion_config.chunk_size",
                message: "Input should be less than or equal to 8192",
              },
            ],
          },
        },
      }),
    );

    await userEvent.type(screen.getByLabelText("Name"), "Handbook");
    await openIngestion();
    await userEvent.clear(screen.getByLabelText("Chunk size"));
    await userEvent.type(screen.getByLabelText("Chunk size"), "1024");
    await userEvent.click(create());

    await waitFor(() =>
      expect(screen.getByLabelText("Chunk size")).toHaveAccessibleDescription(
        "Input should be less than or equal to 8192",
      ),
    );
  });

  it("sends no reranking fields for a collection nobody turned it on for", async () => {
    // Both-or-neither: the backend reads reranking as on only when the model and
    // the key arrive together, so leaving it Off means sending neither.
    await userEvent.type(screen.getByLabelText("Name"), "Handbook");
    await userEvent.click(create());

    await waitFor(() => expect(apiClient.post).toHaveBeenCalled());
    expect(posted()).not.toHaveProperty("rerank_secret_id");
    expect(posted()).not.toHaveProperty("rerank_model");
  });

  it("sends the key and the one model once a reranking key is chosen", async () => {
    // The model is a constant, not a choice: there is one reranker and no
    // endpoint listing them, so choosing the key is choosing to rerank.
    await userEvent.type(screen.getByLabelText("Name"), "Handbook");
    await userEvent.click(screen.getByText("Reranking"));
    await userEvent.click(screen.getByLabelText("Reranking key"));
    await userEvent.click(await screen.findByRole("option", { name: /Cohere key/ }));
    await userEvent.click(create());

    await waitFor(() => expect(apiClient.post).toHaveBeenCalled());
    expect(posted().rerank_secret_id).toBe("cohere-1");
    expect(posted().rerank_model).toBe("rerank-v3.5");
  });

  it("keeps the name and its own settings when the server refuses", async () => {
    // A dialog that clears itself on a refusal makes the refusal cost the whole
    // form, which is how people learn not to open the settings at all.
    vi.mocked(apiClient.post).mockRejectedValue(
      new ApiError(400, "Model profile 'openai default' has no credential configured", {
        error: {
          code: "BAD_REQUEST",
          message: "Model profile 'openai default' has no credential configured",
          details: { profile_id: "b37074c9" },
        },
      }),
    );

    await userEvent.type(screen.getByLabelText("Name"), "Handbook");
    await openIngestion();
    await userEvent.clear(screen.getByLabelText("Chunk size"));
    await userEvent.type(screen.getByLabelText("Chunk size"), "1024");
    await userEvent.click(create());

    await waitFor(() => expect(apiClient.post).toHaveBeenCalled());
    expect(screen.getByLabelText("Name")).toHaveValue("Handbook");
    expect(screen.getByLabelText("Chunk size")).toHaveValue(1024);
  });
});
