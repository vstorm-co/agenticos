import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { MemoryFactsPane } from "./memory-facts-pane";
import { PAGE_SIZE } from "@/components/ui";
import { apiClient } from "@/lib/api-client";
import { ApiError } from "@/lib/api-error";

vi.mock("@/lib/api-client", () => ({
  apiClient: { get: vi.fn(), post: vi.fn(), patch: vi.fn(), delete: vi.fn() },
}));
vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));

const FACT_SHARED = {
  id: "x1",
  agent_id: "a1",
  content: "Acme's fiscal year starts in April.",
  origin: "operator",
  end_user_scope_key: null,
  created_at: "2026-08-30T10:00:00Z",
};
// A fact with no timestamp exercises the guard that renders the "remembered"
// line only when there is one.
const FACT_USER = {
  id: "x2",
  agent_id: "a1",
  content: "Prefers weekly summaries on Fridays.",
  origin: "agent",
  end_user_scope_key: "user:0f3a91b2",
  created_at: null,
};

function factsReturning(items: unknown[], total = items.length) {
  vi.mocked(apiClient.get).mockResolvedValue({ items, total });
}

function lastFactsCall(): string {
  const calls = vi.mocked(apiClient.get).mock.calls.map(([url]) => url as string);
  return calls.filter((url) => url.startsWith("/memory/facts?")).at(-1) ?? "";
}

function wrapper({ children }: { children: ReactNode }) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

function mount(props: Partial<React.ComponentProps<typeof MemoryFactsPane>> = {}) {
  render(<MemoryFactsPane agentId="a1" canEdit scope="all" {...props} />, { wrapper });
}

describe("MemoryFactsPane", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    factsReturning([FACT_SHARED, FACT_USER]);
  });

  it("lists the facts with their partition, and when a timestamped one was remembered", async () => {
    mount();

    expect(await screen.findByText("Acme's fiscal year starts in April.")).toBeInTheDocument();
    expect(screen.getByText("Prefers weekly summaries on Fridays.")).toBeInTheDocument();
    // One operator-seeded shared fact, one agent-written personal one.
    expect(screen.getByText("Operator")).toBeInTheDocument();
    expect(screen.getByText("Agent")).toBeInTheDocument();
    expect(screen.getByText("user:0f3a91b2")).toBeInTheDocument();
    // Only the fact that carries a timestamp shows when it was remembered.
    expect(screen.getAllByText(/^remembered/)).toHaveLength(1);
  });

  it("explains that facts are recalled by meaning, unlike files", async () => {
    mount();
    await screen.findByText("Acme's fiscal year starts in April.");

    expect(screen.getByText(/recalls by meaning . unlike files/)).toBeInTheDocument();
  });

  it("opens the new-fact dialog from the button", async () => {
    mount();
    await screen.findByText("Acme's fiscal year starts in April.");

    await userEvent.click(screen.getByRole("button", { name: "New fact" }));
    expect(await screen.findByLabelText("Fact")).toBeInTheDocument();
  });

  it("filters facts by substring on the server", async () => {
    mount();
    await screen.findByText("Acme's fiscal year starts in April.");

    await userEvent.type(screen.getByPlaceholderText("Filter facts…"), "fiscal");

    await waitFor(() => expect(lastFactsCall()).toContain("q=fiscal"));
  });

  it("uses the partition the panel gave it", async () => {
    mount({ scope: "shared" });

    await waitFor(() => expect(lastFactsCall()).toContain("partition=shared"));
  });

  it("confirms before forgetting a fact", async () => {
    vi.mocked(apiClient.delete).mockResolvedValue(undefined);
    mount();
    await screen.findByText("Acme's fiscal year starts in April.");

    await userEvent.click(screen.getAllByRole("button", { name: "Forget fact" })[0]!);
    await userEvent.click(screen.getByRole("button", { name: "Forget" }));

    await waitFor(() => expect(apiClient.delete).toHaveBeenCalledWith("/memory/facts/x1"));
  });

  it("backs out of forgetting without deleting anything", async () => {
    mount();
    await screen.findByText("Acme's fiscal year starts in April.");

    await userEvent.click(screen.getAllByRole("button", { name: "Forget fact" })[0]!);
    const dialog = await screen.findByRole("dialog");
    await userEvent.click(within(dialog).getByRole("button", { name: "Cancel" }));

    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    expect(apiClient.delete).not.toHaveBeenCalled();
  });

  it("says the shelf is empty when the agent has remembered nothing", async () => {
    factsReturning([], 0);
    mount();

    expect(await screen.findByText("No facts yet")).toBeInTheDocument();
  });

  it("distinguishes no matches from no facts", async () => {
    factsReturning([], 0);
    mount();
    await screen.findByText("No facts yet");

    await userEvent.type(screen.getByPlaceholderText("Filter facts…"), "zzz");

    expect(await screen.findByText("No facts match")).toBeInTheDocument();
  });

  it("shows the failure instead of an empty shelf", async () => {
    vi.mocked(apiClient.get).mockRejectedValue(new ApiError(502, "upstream", null));
    mount();

    expect(await screen.findByText("Something went wrong")).toBeInTheDocument();
  });

  it("gives a viewer nothing to delete with", async () => {
    mount({ canEdit: false });
    await screen.findByText("Acme's fiscal year starts in April.");

    expect(screen.queryByRole("button", { name: "Forget fact" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Clear all facts" })).not.toBeInTheDocument();
  });

  it("clears every fact from the pane, behind a confirm", async () => {
    vi.mocked(apiClient.delete).mockResolvedValue(undefined);
    mount();
    await screen.findByText("Acme's fiscal year starts in April.");

    await userEvent.click(screen.getByRole("button", { name: "Clear all facts" }));
    const dialog = await screen.findByRole("dialog");
    await userEvent.click(within(dialog).getByRole("button", { name: "Clear all facts" }));

    await waitFor(() => expect(apiClient.delete).toHaveBeenCalledWith("/memory/facts?agent_id=a1"));
  });

  it("backs out of clearing facts without deleting anything", async () => {
    mount();
    await screen.findByText("Acme's fiscal year starts in April.");

    await userEvent.click(screen.getByRole("button", { name: "Clear all facts" }));
    const dialog = await screen.findByRole("dialog");
    await userEvent.click(within(dialog).getByRole("button", { name: "Cancel" }));

    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    expect(apiClient.delete).not.toHaveBeenCalled();
  });

  it("retries a failed load rather than stranding an error", async () => {
    vi.mocked(apiClient.get)
      .mockRejectedValueOnce(new ApiError(502, "upstream", null))
      .mockResolvedValue({ items: [FACT_SHARED], total: 1 });
    mount();
    expect(await screen.findByText("Something went wrong")).toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: "Retry" }));

    expect(await screen.findByText("Acme's fiscal year starts in April.")).toBeInTheDocument();
  });

  it("steps back after forgetting the last fact of a later page", async () => {
    // Forgetting the one fact on a later page empties it and hides the pager, so the
    // pane must fall back to the previous page.
    let total = PAGE_SIZE + 1;
    const factAt = (i: number) => ({ ...FACT_SHARED, id: `x-${i}`, content: `fact-${i}` });
    vi.mocked(apiClient.get).mockImplementation((url: string) => {
      const skip = Number(new URLSearchParams(url.split("?")[1] ?? "").get("skip") ?? 0);
      const count = Math.max(0, Math.min(total - skip, PAGE_SIZE));
      return Promise.resolve({
        items: Array.from({ length: count }, (_, i) => factAt(skip + i)),
        total,
      });
    });
    vi.mocked(apiClient.delete).mockImplementation(() => {
      total -= 1;
      return Promise.resolve(undefined);
    });
    mount();
    await screen.findByText("fact-0");

    await userEvent.click(screen.getByRole("button", { name: /next/i }));
    await screen.findByText(`fact-${PAGE_SIZE}`);

    await userEvent.click(screen.getByRole("button", { name: "Forget fact" }));
    await userEvent.click(screen.getByRole("button", { name: "Forget" }));

    expect(await screen.findByText("fact-0")).toBeInTheDocument();
  });
});
