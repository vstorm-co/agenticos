import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import AdminConversationsPage from "./page";
import { apiClient } from "@/lib/api-client";

/**
 * What this screen says when one of its lists does not answer.
 *
 * It said "No conversations found." - the hook has always held the reason and
 * the page never destructured it, so a 403, a 502 and a deployment with no
 * threads in it were the same sentence. The owner list next to it was worse
 * still: it forwarded to a route that did not exist and 422'd on every load, and
 * the only visible symptom was a filter with one item in it.
 */
vi.mock("@/lib/api-client", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api-client")>("@/lib/api-client");
  return {
    ...actual,
    apiClient: { get: vi.fn(), post: vi.fn(), patch: vi.fn(), delete: vi.fn() },
  };
});
vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));

function wrapper({ children }: { children: ReactNode }) {
  return (
    <QueryClientProvider
      client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}
    >
      {children}
    </QueryClientProvider>
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(apiClient.get).mockResolvedValue({ items: [], total: 0 });
});

describe("the admin conversations screen", () => {
  it("says an empty table is empty when it really is", async () => {
    render(<AdminConversationsPage />, { wrapper });

    expect(await screen.findByText("No conversations found.")).toBeInTheDocument();
  });

  it("says what went wrong instead, when a list was refused", async () => {
    vi.mocked(apiClient.get).mockRejectedValue(new Error("Forbidden"));
    render(<AdminConversationsPage />, { wrapper });

    expect(await screen.findByText("Forbidden")).toBeInTheDocument();
    expect(screen.queryByText("No conversations found.")).toBeNull();
  });
});
