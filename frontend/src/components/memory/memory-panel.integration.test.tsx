import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { MemoryPanel } from "./memory-panel";
import { apiClient } from "@/lib/api-client";
import { useAuthStore } from "@/stores";

vi.mock("@/lib/api-client", () => ({
  apiClient: { get: vi.fn(), post: vi.fn(), patch: vi.fn(), delete: vi.fn() },
}));
vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));
vi.mock("@/components/chat/markdown-content", () => ({
  MarkdownContent: ({ content }: { content: string }) => (
    <div data-testid="rendered">{content}</div>
  ),
}));

const FILE = {
  id: "f1",
  name: "user-preferences",
  description: "tone",
  format: "md",
  kind: "note",
  origin: "operator",
  owner_key: null,
  size_bytes: 40,
};
const FACT = {
  id: "x1",
  agent_id: "a1",
  content: "Acme's fiscal year starts in April.",
  owner_key: null,
  created_at: null,
};

function apiReturning() {
  vi.mocked(apiClient.get).mockImplementation((url: string) => {
    if (url.startsWith("/memory/facts")) return Promise.resolve({ items: [FACT], total: 1 });
    return Promise.resolve({ items: [FILE], total: 1 });
  });
}

function lastFilesCall(): string {
  const calls = vi.mocked(apiClient.get).mock.calls.map(([url]) => url as string);
  return calls.filter((url) => url.startsWith("/memory/files?")).at(-1) ?? "";
}

function wrapper({ children }: { children: ReactNode }) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

function mount(props: Partial<React.ComponentProps<typeof MemoryPanel>> = {}) {
  render(
    <MemoryPanel
      agentId="a1"
      canEdit
      backend="native"
      enableFiles
      enableFacts
      allowPersonal
      {...props}
    />,
    { wrapper },
  );
}

describe("MemoryPanel", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    apiReturning();
    // No identified person by default, so the "mine" filter is absent unless a
    // test sets one; reset so a user set by one test does not leak into the next.
    useAuthStore.setState({ user: null });
  });

  it("shows how memory is configured, defaulting to the files half", async () => {
    mount();

    expect(screen.getByText("Personal memory on")).toBeInTheDocument();
    expect(screen.getByText("Backend: native")).toBeInTheDocument();
    expect(await screen.findByText("user-preferences")).toBeInTheDocument();
  });

  it("reflects the mem0 backend in its badge", () => {
    mount({ backend: "mem0" });

    expect(screen.getByText("Personal memory on")).toBeInTheDocument();
    expect(screen.getByText("Backend: mem0")).toBeInTheDocument();
  });

  it("says where a mem0 agent's facts are instead of listing an empty native store", async () => {
    // Every native fact route refuses a mem0-backed agent, so mounting the pane would
    // ask three times and render an error with a live "New fact" button above it.
    mount({ backend: "mem0" });
    await screen.findByText("user-preferences");

    await userEvent.click(screen.getByRole("button", { name: "Facts" }));

    expect(await screen.findByText("Facts live in mem0")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "New fact" })).not.toBeInTheDocument();
    const factCalls = vi
      .mocked(apiClient.get)
      .mock.calls.map(([url]) => url as string)
      .filter((url) => url.startsWith("/memory/facts"));
    expect(factCalls).toHaveLength(0);
  });

  it("hides the danger zone for a mem0 agent, whose clear can only fail", async () => {
    // The combined clear refuses before deleting anything, rather than dropping the
    // native files and leaving every mem0 fact recallable.
    mount({ backend: "mem0" });
    await screen.findByText("user-preferences");

    expect(screen.queryByRole("button", { name: "Clear all memory" })).not.toBeInTheDocument();
  });

  it("shows a no-personal badge when personal memory is off", () => {
    mount({ allowPersonal: false });

    expect(screen.getByText("No personal memory")).toBeInTheDocument();
  });

  it("filters both halves by the organisation owner control", async () => {
    mount();
    await screen.findByText("user-preferences");

    await userEvent.click(screen.getByRole("button", { name: "All" }));
    await userEvent.click(screen.getByRole("button", { name: "Organisation" }));

    await waitFor(() => expect(lastFilesCall()).toContain("owner=org"));
  });

  it("switches between the files and facts halves", async () => {
    mount();
    await screen.findByText("user-preferences");

    await userEvent.click(screen.getByRole("button", { name: "Facts" }));
    expect(await screen.findByText("Acme's fiscal year starts in April.")).toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: "Files" }));
    expect(await screen.findByText("user-preferences")).toBeInTheDocument();
  });

  it("offers no switcher when only files are enabled", async () => {
    mount({ enableFacts: false });

    await screen.findByText("user-preferences");
    expect(screen.queryByRole("button", { name: "Facts" })).not.toBeInTheDocument();
  });

  it("shows the facts half directly when only facts are enabled", async () => {
    mount({ enableFiles: false });

    expect(await screen.findByText("Acme's fiscal year starts in April.")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Files" })).not.toBeInTheDocument();
  });

  it("says memory is off when neither half is enabled", () => {
    mount({ enableFiles: false, enableFacts: false });

    expect(screen.getByText("Memory is off")).toBeInTheDocument();
  });

  it("filters both halves to the person stores", async () => {
    mount();
    await screen.findByText("user-preferences");

    await userEvent.click(screen.getByRole("button", { name: "People" }));

    await waitFor(() => expect(lastFilesCall()).toContain("owner=person"));
  });

  it("clears all memory from the danger zone, behind a confirm", async () => {
    vi.mocked(apiClient.delete).mockResolvedValue(undefined);
    mount();
    await screen.findByText("user-preferences");

    // The card's button and the confirm's share the label; the card's is first.
    await userEvent.click(screen.getAllByRole("button", { name: "Clear all memory" })[0]!);
    const dialog = await screen.findByRole("dialog");
    await userEvent.click(within(dialog).getByRole("button", { name: "Clear all memory" }));

    await waitFor(() => expect(apiClient.delete).toHaveBeenCalledWith("/memory?agent_id=a1"));
  });

  it("backs out of clearing memory without deleting anything", async () => {
    mount();
    await screen.findByText("user-preferences");

    await userEvent.click(screen.getAllByRole("button", { name: "Clear all memory" })[0]!);
    const dialog = await screen.findByRole("dialog");
    await userEvent.click(within(dialog).getByRole("button", { name: "Cancel" }));

    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    expect(apiClient.delete).not.toHaveBeenCalled();
  });

  it("keeps the danger zone from a viewer but lets them add their own personal", async () => {
    mount({ canEdit: false });
    await screen.findByText("user-preferences");

    // A member may seed their own personal memory through the create dialog...
    expect(screen.getByRole("button", { name: "New file" })).toBeInTheDocument();
    // ...but the destructive operator control stays hidden.
    expect(screen.queryByRole("button", { name: "Clear all memory" })).not.toBeInTheDocument();
  });

  it("starts a viewer on the organisation store, not the all filter that would 404", async () => {
    useAuthStore.setState({
      user: { id: "u-7", email: "viewer@example.com", is_active: true, created_at: "2026-01-01" },
    });
    mount({ canEdit: false });
    await screen.findByText("user-preferences");

    await waitFor(() => expect(lastFilesCall()).toContain("owner=org"));
    // A viewer cannot list every partition or the per-user store, so those
    // filters are not even offered.
    expect(screen.queryByRole("button", { name: "All" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "People" })).not.toBeInTheDocument();
  });

  it("lets a viewer filter to their own memory", async () => {
    useAuthStore.setState({
      user: { id: "u-7", email: "viewer@example.com", is_active: true, created_at: "2026-01-01" },
    });
    mount({ canEdit: false });
    await screen.findByText("user-preferences");

    await userEvent.click(screen.getByRole("button", { name: "Mine" }));
    await waitFor(() => expect(decodeURIComponent(lastFilesCall())).toContain("owner=person:u-7"));

    // ...and back to the shared store.
    await userEvent.click(screen.getByRole("button", { name: "Organisation" }));
    await waitFor(() => expect(lastFilesCall()).toContain("owner=org"));
  });
});
