import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { MemoryPanel } from "./memory-panel";
import { apiClient } from "@/lib/api-client";

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
  end_user_scope_key: null,
  size_bytes: 40,
};
const FACT = {
  id: "x1",
  agent_id: "a1",
  content: "Acme's fiscal year starts in April.",
  end_user_scope_key: null,
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
      partition="shared"
      backend="native"
      enableFiles
      enableFacts
      {...props}
    />,
    { wrapper },
  );
}

describe("MemoryPanel", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    apiReturning();
  });

  it("shows how memory is configured, defaulting to the files half", async () => {
    mount();

    expect(screen.getByText("Partition: shared")).toBeInTheDocument();
    expect(screen.getByText("Backend: native")).toBeInTheDocument();
    expect(await screen.findByText("user-preferences")).toBeInTheDocument();
  });

  it("reflects a per-user, mem0-backed configuration in its badges", () => {
    mount({ partition: "per_user", backend: "mem0" });

    expect(screen.getByText("Partition: per-user")).toBeInTheDocument();
    expect(screen.getByText("Backend: mem0")).toBeInTheDocument();
  });

  it("filters both halves by the shared scope control", async () => {
    mount();
    await screen.findByText("user-preferences");

    await userEvent.click(screen.getByRole("button", { name: "All" }));
    await userEvent.click(screen.getByRole("button", { name: "Shared" }));

    await waitFor(() => expect(lastFilesCall()).toContain("partition=shared"));
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

  it("passes read-only through to a viewer", async () => {
    mount({ canEdit: false });
    await screen.findByText("user-preferences");

    expect(screen.queryByRole("button", { name: "New file" })).not.toBeInTheDocument();
  });
});
