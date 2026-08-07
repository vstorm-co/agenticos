import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import RAGPage from "./page";
import * as ragApi from "@/lib/rag-api";

/**
 * The collection picker at the top of the vector-store page.
 *
 * A collection's size is how one is told from another while choosing, and
 * nothing else. Radix draws the selected item's `ItemText` in the closed
 * trigger, so in `children` the count followed the choice out - into a trigger
 * that sits four inches from the same number, which the page prints beside it
 * for the collection actually selected.
 */

vi.mock("@/lib/rag-api");
vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));
vi.mock("next/navigation", () => ({ useRouter: () => ({ replace: vi.fn(), push: vi.fn() }) }));
vi.mock("@/hooks", () => ({
  useAuth: () => ({ user: { id: "u1", email: "admin@acme.test", is_app_admin: true } }),
  usePollWhileIngesting: vi.fn(),
}));
vi.mock("@/lib/api-client", () => ({
  apiClient: { get: vi.fn().mockResolvedValue({ formats: [".pdf"] }) },
}));

function wrapper({ children }: { children: ReactNode }) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

const SIZES: Record<string, number> = { eng_docs: 4210, sales_docs: 1 };

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(ragApi.listCollections).mockResolvedValue({ items: ["eng_docs", "sales_docs"] });
  vi.mocked(ragApi.getCollectionInfo).mockImplementation(async (name: string) => ({
    name,
    total_vectors: SIZES[name] ?? 0,
    dim: 3072,
    indexing_status: "idle",
  }));
  vi.mocked(ragApi.listTrackedDocuments).mockResolvedValue({ items: [], total: 0 });
  vi.mocked(ragApi.listSyncSources).mockResolvedValue({ items: [], total: 0 });
  vi.mocked(ragApi.listSyncLogs).mockResolvedValue({ items: [], total: 0 });
  vi.mocked(ragApi.listConnectors).mockResolvedValue({ items: [] });
});

describe("the collection picker", () => {
  it("sizes every collection in the list, so two can be told apart", async () => {
    render(<RAGPage />, { wrapper });

    await userEvent.click(await screen.findByRole("combobox"));

    // Matched inside each option rather than through its accessible name: the
    // size is `trailing`, and Radix names an item by its `ItemText` alone.
    const eng = await screen.findByRole("option", { name: "eng_docs" });
    expect(within(eng).getByText("4,210 vectors")).toBeVisible();

    // A count is an ICU plural, not English with an `s` glued on.
    const sales = screen.getByRole("option", { name: "sales_docs" });
    expect(within(sales).getByText("1 vector")).toBeVisible();
  });

  it("does not repeat the size on the closed trigger", async () => {
    render(<RAGPage />, { wrapper });

    const picker = await screen.findByRole("combobox");
    await userEvent.click(picker);
    await userEvent.click(await screen.findByRole("option", { name: "sales_docs" }));

    expect(picker).toHaveTextContent("sales_docs");
    expect(picker).not.toHaveTextContent("vector");
  });

  it("prints the chosen collection's size beside the picker, where it belongs", async () => {
    // Which is why the trigger repeating it was noise rather than information:
    // the number is already on the page, next to the dimension it was written
    // at, for the one collection the answer is about.
    render(<RAGPage />, { wrapper });

    expect(await screen.findByText("4,210 vectors · 3072d")).toBeVisible();
  });
});
