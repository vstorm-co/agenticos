import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { RerankDialog } from "./rerank-dialog";
import { apiClient, ApiError } from "@/lib/api-client";

/**
 * The edit dialog is the whole point of "reranking can be changed after
 * creation": the create dialog sets it once, this turns it on, swaps its key or
 * turns it off. What it must get right is the pair it sends - a key and the one
 * model, or two nulls - because that pair is how the backend tells "change
 * reranking" from "leave it alone".
 */

vi.mock("@/lib/api-client", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/api-client")>()),
  apiClient: { get: vi.fn(), post: vi.fn(), patch: vi.fn(), delete: vi.fn() },
}));
const toastError = vi.fn();
vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: (m: string) => toastError(m) } }));

const SECRETS = {
  items: [
    { id: "co-1", name: "Cohere prod", hint: "4242", purpose: "cohere", kind: "api_key" },
    // Not a rerank key: it must never be offered as one that can pay for reranking.
    { id: "tav-1", name: "Tavily", hint: "9999", purpose: "tavily", kind: "api_key" },
  ],
  total: 2,
};

function wrapper({ children }: { children: ReactNode }) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(apiClient.get).mockImplementation(async (path: string) => {
    if (path === "/secrets") return SECRETS;
    if (path === "/me/permissions")
      return { organization_id: "org-1", role: "builder", is_app_admin: false, permissions: [] };
    return { items: [], total: 0 };
  });
});

describe("choosing a key", () => {
  it("offers only keys that can pay for reranking", async () => {
    render(
      <RerankDialog
        open
        onOpenChange={vi.fn()}
        rerankSecretId={null}
        collectionName="handbook_x"
        onSave={vi.fn()}
      />,
      { wrapper },
    );
    await userEvent.click(screen.getByLabelText("Reranking key"));

    expect(await screen.findByRole("option", { name: /Cohere prod/ })).toBeInTheDocument();
    expect(screen.queryByRole("option", { name: /Tavily/ })).toBeNull();
  });

  it("turning it on sends the one model paired with the chosen key", async () => {
    const onSave = vi.fn().mockResolvedValue({});
    const onOpenChange = vi.fn();
    render(
      <RerankDialog
        open
        onOpenChange={onOpenChange}
        rerankSecretId={null}
        collectionName="handbook_x"
        onSave={onSave}
      />,
      { wrapper },
    );

    await userEvent.click(screen.getByLabelText("Reranking key"));
    await userEvent.click(await screen.findByRole("option", { name: /Cohere prod/ }));
    await userEvent.click(screen.getByRole("button", { name: "Save" }));

    expect(onSave).toHaveBeenCalledWith({
      rerank_model: "rerank-v3.5",
      rerank_secret_id: "co-1",
    });
    await waitFor(() => expect(onOpenChange).toHaveBeenCalledWith(false));
  });

  it("turning it off sends the pair as two nulls", async () => {
    const onSave = vi.fn().mockResolvedValue({});
    render(
      <RerankDialog
        open
        onOpenChange={vi.fn()}
        rerankSecretId="co-1"
        collectionName="handbook_x"
        onSave={onSave}
      />,
      { wrapper },
    );

    await userEvent.click(screen.getByLabelText("Reranking key"));
    await userEvent.click(await screen.findByRole("option", { name: "Off" }));
    await userEvent.click(screen.getByRole("button", { name: "Save" }));

    expect(onSave).toHaveBeenCalledWith({ rerank_model: null, rerank_secret_id: null });
  });

  it("cannot be saved until something changes", async () => {
    render(
      <RerankDialog
        open
        onOpenChange={vi.fn()}
        rerankSecretId="co-1"
        collectionName="handbook_x"
        onSave={vi.fn()}
      />,
      { wrapper },
    );

    expect(screen.getByRole("button", { name: "Save" })).toBeDisabled();
  });
});

describe("when the save is refused", () => {
  it("shows a key the server named as wrong beside the picker", async () => {
    const onSave = vi.fn().mockRejectedValue(
      new ApiError(422, "Invalid", {
        error: {
          code: "VALIDATION_ERROR",
          message: "Invalid",
          details: {
            fields: [
              {
                field: "rerank_secret_id",
                message: "That key is for tavily; reranking runs through Cohere.",
              },
            ],
          },
        },
      }),
    );
    render(
      <RerankDialog
        open
        onOpenChange={vi.fn()}
        rerankSecretId={null}
        collectionName="handbook_x"
        onSave={onSave}
      />,
      { wrapper },
    );

    await userEvent.click(screen.getByLabelText("Reranking key"));
    await userEvent.click(await screen.findByRole("option", { name: /Cohere prod/ }));
    await userEvent.click(screen.getByRole("button", { name: "Save" }));

    expect(await screen.findByText(/That key is for tavily/)).toBeInTheDocument();
  });

  it("toasts a refusal that names no field", async () => {
    const onSave = vi.fn().mockRejectedValue(new Error("boom"));
    render(
      <RerankDialog
        open
        onOpenChange={vi.fn()}
        rerankSecretId={null}
        collectionName="handbook_x"
        onSave={onSave}
      />,
      { wrapper },
    );

    await userEvent.click(screen.getByLabelText("Reranking key"));
    await userEvent.click(await screen.findByRole("option", { name: /Cohere prod/ }));
    await userEvent.click(screen.getByRole("button", { name: "Save" }));

    await waitFor(() => expect(toastError).toHaveBeenCalledWith("boom"));
  });
});

describe("what it shows when reopened", () => {
  it("discards an abandoned pick, re-seeding from the server on reopen", async () => {
    // Save is disabled only when the draft equals what the server holds, so it
    // is the observable proof of a re-seed: if the abandoned pick survived, the
    // draft would differ from the server and Save would be live.
    const props = {
      onOpenChange: vi.fn(),
      rerankSecretId: "co-1" as string | null,
      collectionName: "handbook_x",
      onSave: vi.fn(),
    };
    const { rerender } = render(<RerankDialog open {...props} />, { wrapper });

    await userEvent.click(screen.getByLabelText("Reranking key"));
    await userEvent.click(await screen.findByRole("option", { name: "Off" }));
    expect(screen.getByRole("button", { name: "Save" })).toBeEnabled();

    // Closed, then reopened against the unchanged collection: the draft goes back
    // to its key and Save falls dormant again.
    rerender(<RerankDialog open={false} {...props} />);
    rerender(<RerankDialog open {...props} />);

    expect(screen.getByRole("button", { name: "Save" })).toBeDisabled();
  });

  it("follows the server's value when reranking is changed elsewhere while open", async () => {
    // The pair moving under an open dialog (a save in another tab) re-seeds the
    // draft too - Save stays dormant because the draft tracked the change rather
    // than staying on the key that is no longer set.
    const props = {
      open: true,
      onOpenChange: vi.fn(),
      collectionName: "handbook_x",
      onSave: vi.fn(),
    };
    const { rerender } = render(<RerankDialog rerankSecretId="co-1" {...props} />, { wrapper });
    rerender(<RerankDialog rerankSecretId={null} {...props} />);

    expect(screen.getByRole("button", { name: "Save" })).toBeDisabled();
  });
});
