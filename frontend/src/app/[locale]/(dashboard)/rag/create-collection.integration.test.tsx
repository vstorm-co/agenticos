import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { type ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import RAGPage from "./page";
import { apiClient } from "@/lib/api-client";
import { ApiError } from "@/lib/api-error";
import { MAX_COLLECTION_NAME_LENGTH } from "@/lib/rag-api";

/**
 * What `/rag` says when the server refuses a collection name.
 *
 * This is the only screen in the product that creates a collection by name, and
 * it threw the explanation away: `catch {}` bound nothing, so a malformed name,
 * a reserved one, one too long and one another organization already holds all
 * arrived as "Failed to create collection" - on a form whose only input is the
 * thing that was wrong (#436).
 *
 * Each assertion is on the *sentence*, not on a toast or an alert existing:
 * "something failed" is what the page already said.
 */

vi.mock("@/lib/api-client", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api-client")>("@/lib/api-client");
  return {
    ...actual,
    apiClient: { get: vi.fn(), post: vi.fn(), patch: vi.fn(), delete: vi.fn() },
  };
});
vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));
vi.mock("@/hooks", async () => {
  const actual = await vi.importActual<typeof import("@/hooks")>("@/hooks");
  return { ...actual, useAuth: () => ({ user: { id: "u1", is_app_admin: true } }) };
});

/** The envelope `app/api/exception_handlers.py` really answers with. */
function refusal(status: number, code: string, message: string, details: unknown): ApiError {
  const body = { error: { code, message, details } };
  return new ApiError(status, message, body);
}

const MALFORMED =
  "A collection name must start with a letter and hold only letters, numbers and underscores";
const TAKEN = "A collection named 'handbook' already exists";

function serve() {
  vi.mocked(apiClient.get).mockImplementation(async (path: string) => {
    if (path === "/rag/collections") return { items: [] };
    if (path.endsWith("/supported-formats")) return { formats: [".pdf"] };
    return { items: [], total: 0 };
  });
}

function wrapper({ children }: { children: ReactNode }) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

async function openTheForm() {
  await act(async () => {
    render(<RAGPage />, { wrapper });
  });
  await userEvent.click(await screen.findByRole("button", { name: "New collection" }));
  return screen.getByPlaceholderText("collection_name");
}

describe("creating a collection on /rag", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    serve();
  });

  it("says which rule refused the name, beside the name", async () => {
    vi.mocked(apiClient.post).mockRejectedValue(
      refusal(400, "BAD_REQUEST", MALFORMED, { collection: "my-handbook" }),
    );
    const input = await openTheForm();

    await userEvent.type(input, "my-handbook");
    await userEvent.click(screen.getByRole("button", { name: "Create" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(MALFORMED);
  });

  it("tells a name that is taken apart from a name that is wrong", async () => {
    vi.mocked(apiClient.post).mockRejectedValue(
      refusal(409, "ALREADY_EXISTS", TAKEN, { collection: "handbook" }),
    );
    const input = await openTheForm();

    await userEvent.type(input, "handbook");
    await userEvent.click(screen.getByRole("button", { name: "Create" }));

    // A different sentence, and one whose next action is different: pick
    // another name rather than fix the one you typed.
    expect(await screen.findByRole("alert")).toHaveTextContent(TAKEN);
    expect(screen.queryByText(MALFORMED)).toBeNull();
  });

  it("keeps what was typed so it can be corrected", async () => {
    vi.mocked(apiClient.post).mockRejectedValue(
      refusal(400, "BAD_REQUEST", MALFORMED, { collection: "my-handbook" }),
    );
    const input = await openTheForm();

    await userEvent.type(input, "my-handbook");
    await userEvent.click(screen.getByRole("button", { name: "Create" }));
    await screen.findByRole("alert");

    expect(input).toHaveValue("my-handbook");
    expect(input).toHaveAttribute("aria-invalid", "true");
  });

  it("clears the refusal once the name changes", async () => {
    vi.mocked(apiClient.post).mockRejectedValue(
      refusal(400, "BAD_REQUEST", MALFORMED, { collection: "my-handbook" }),
    );
    const input = await openTheForm();

    await userEvent.type(input, "my-handbook");
    await userEvent.click(screen.getByRole("button", { name: "Create" }));
    await screen.findByRole("alert");

    await userEvent.type(input, "s");

    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("stops a name at the length the server would refuse it for", async () => {
    const input = await openTheForm();

    await userEvent.type(input, "a".repeat(MAX_COLLECTION_NAME_LENGTH + 10));

    expect(input).toHaveValue("a".repeat(MAX_COLLECTION_NAME_LENGTH));
  });
});
