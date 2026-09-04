import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { MemoryFilesPane } from "./memory-files-pane";
import { apiClient } from "@/lib/api-client";
import { ApiError } from "@/lib/api-error";

vi.mock("@/lib/api-client", () => ({
  apiClient: { get: vi.fn(), post: vi.fn(), patch: vi.fn(), delete: vi.fn() },
}));
vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));
vi.mock("@/components/chat/markdown-content", () => ({
  MarkdownContent: ({ content }: { content: string }) => (
    <div data-testid="rendered">{content}</div>
  ),
}));

const OPERATOR = {
  id: "f1",
  name: "user-preferences",
  description: "tone",
  format: "md",
  kind: "note",
  origin: "operator",
  end_user_scope_key: null,
  size_bytes: 40,
};
const AGENT = {
  id: "f2",
  name: "acme-notes",
  description: "learned",
  format: "md",
  kind: "memory",
  origin: "agent",
  end_user_scope_key: "user:0f3a91b2",
  size_bytes: 30,
};
const BODY_OPERATOR = {
  ...OPERATOR,
  agent_id: "a1",
  content: "Prefer bullets.",
  created_at: null,
  updated_at: null,
};
const BODY_AGENT = {
  ...AGENT,
  agent_id: "a1",
  content: "Fiscal year starts April.",
  created_at: null,
  updated_at: null,
};

function listReturning(items: unknown[], total = items.length) {
  vi.mocked(apiClient.get).mockImplementation((url: string) => {
    if (url === "/memory/files/f1") return Promise.resolve(BODY_OPERATOR);
    if (url === "/memory/files/f2") return Promise.resolve(BODY_AGENT);
    return Promise.resolve({ items, total });
  });
}

function lastListCall(): string {
  const calls = vi.mocked(apiClient.get).mock.calls.map(([url]) => url as string);
  return calls.filter((url) => url.startsWith("/memory/files?")).at(-1) ?? "";
}

function wrapper({ children }: { children: ReactNode }) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

function mount(props: Partial<React.ComponentProps<typeof MemoryFilesPane>> = {}) {
  render(<MemoryFilesPane agentId="a1" canEdit scope="all" {...props} />, { wrapper });
}

describe("MemoryFilesPane", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    listReturning([OPERATOR, AGENT]);
  });

  it("lists the files with their origin and partition", async () => {
    mount();

    expect(await screen.findByText("user-preferences")).toBeInTheDocument();
    expect(screen.getByText("acme-notes")).toBeInTheDocument();
    expect(screen.getByText("Operator")).toBeInTheDocument();
    expect(screen.getByText("Agent")).toBeInTheDocument();
    expect(screen.getByText("user:0f3a91b2")).toBeInTheDocument();
  });

  it("shows an error with retry when the file detail fails to load, and recovers", async () => {
    // A failed detail GET must not leave the dialog on a permanent skeleton; Retry
    // refetches and, on success, shows the editor.
    let detailCalls = 0;
    vi.mocked(apiClient.get).mockImplementation((url: string) => {
      if (url.startsWith("/memory/files/f")) {
        detailCalls += 1;
        return detailCalls === 1
          ? Promise.reject(new ApiError(502, "upstream", null))
          : Promise.resolve(BODY_OPERATOR);
      }
      return Promise.resolve({ items: [OPERATOR], total: 1 });
    });
    mount();
    await userEvent.click(await screen.findByText("user-preferences"));

    expect(await screen.findByText("Something went wrong")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Retry" }));

    expect(await screen.findByTestId("rendered")).toHaveTextContent("Prefer bullets.");
  });

  it("confines the listing to the partition the panel gave it", async () => {
    mount({ scope: "shared" });

    await waitFor(() => expect(lastListCall()).toContain("partition=shared"));
  });

  it("orders by recent change when asked", async () => {
    mount();
    await screen.findByText("user-preferences");

    await userEvent.click(screen.getByRole("button", { name: "Name" }));
    await userEvent.click(screen.getByRole("button", { name: "Recently updated" }));

    await waitFor(() => expect(lastListCall()).toContain("sort=updated"));
  });

  it("searches names and descriptions on the server", async () => {
    mount();
    await screen.findByText("user-preferences");

    await userEvent.type(screen.getByPlaceholderText("Search memory…"), "acme");

    await waitFor(() => expect(lastListCall()).toContain("q=acme"));
  });

  it("pages when there is more than one page", async () => {
    listReturning([OPERATOR, AGENT], 120);
    mount();
    await screen.findByText("user-preferences");

    await userEvent.click(screen.getByRole("button", { name: /next/i }));

    await waitFor(() => expect(lastListCall()).toContain("skip=50"));
  });

  it("opens the new-file dialog", async () => {
    mount();
    await screen.findByText("user-preferences");

    await userEvent.click(screen.getByRole("button", { name: "New file" }));

    expect(
      await screen.findByText("A trusted reference file, available to the agent on every run."),
    ).toBeInTheDocument();
  });

  it("saves an edit, sending the change and closing the editor", async () => {
    vi.mocked(apiClient.patch).mockResolvedValue({
      ...BODY_OPERATOR,
      description: "tone sharpened",
    });
    mount();

    await userEvent.click(await screen.findByText("user-preferences"));
    const dialog = await screen.findByRole("dialog");
    await userEvent.type(within(dialog).getByLabelText("Description"), " sharpened");
    await userEvent.click(within(dialog).getByRole("button", { name: "Save" }));

    await waitFor(() =>
      expect(apiClient.patch).toHaveBeenCalledWith(
        "/memory/files/f1",
        expect.objectContaining({ description: "tone sharpened" }),
      ),
    );
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
  });

  it("promotes an agent file and reflects the new trust in the open editor", async () => {
    // The consequence, not the call: a promote must flip the file to trusted in
    // the editor still on screen, so the operator sees it worked and cannot
    // re-fire it. Without writing the result back over the detail cache, the
    // editor keeps rendering the agent-authored, un-promotable state.
    vi.mocked(apiClient.post).mockResolvedValue({ ...BODY_AGENT, origin: "operator" });
    mount();

    await userEvent.click(await screen.findByText("acme-notes"));
    const dialog = await screen.findByRole("dialog");
    expect(within(dialog).getByRole("button", { name: "Promote to trusted" })).toBeInTheDocument();

    await userEvent.click(within(dialog).getByRole("button", { name: "Promote to trusted" }));

    await waitFor(() =>
      expect(apiClient.post).toHaveBeenCalledWith("/memory/files/f2/promote", {}),
    );
    await waitFor(() =>
      expect(
        within(dialog).queryByRole("button", { name: "Promote to trusted" }),
      ).not.toBeInTheDocument(),
    );
  });

  it("dismisses the editor by Cancel, and closes it on Escape", async () => {
    mount();

    await userEvent.click(await screen.findByText("user-preferences"));
    const dialog = await screen.findByRole("dialog");
    await userEvent.click(within(dialog).getByRole("button", { name: "Cancel" }));
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());

    await userEvent.click(screen.getByText("user-preferences"));
    await screen.findByRole("dialog");
    await userEvent.keyboard("{Escape}");
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
  });

  it("confirms before deleting a file", async () => {
    vi.mocked(apiClient.delete).mockResolvedValue(undefined);
    mount();
    await screen.findByText("user-preferences");

    await userEvent.click(screen.getByRole("button", { name: "Delete user-preferences" }));
    await userEvent.click(screen.getByRole("button", { name: "Delete" }));

    await waitFor(() => expect(apiClient.delete).toHaveBeenCalledWith("/memory/files/f1"));
  });

  it("backs out of a delete without removing anything", async () => {
    mount();
    await screen.findByText("user-preferences");

    await userEvent.click(screen.getByRole("button", { name: "Delete user-preferences" }));
    const dialog = await screen.findByRole("dialog");
    await userEvent.click(within(dialog).getByRole("button", { name: "Cancel" }));

    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    expect(apiClient.delete).not.toHaveBeenCalled();
  });

  it("says the shelf is empty when the agent has remembered nothing", async () => {
    listReturning([], 0);
    mount();

    expect(await screen.findByText("No files yet")).toBeInTheDocument();
  });

  it("distinguishes no matches from no files", async () => {
    listReturning([], 0);
    mount();
    await screen.findByText("No files yet");

    await userEvent.type(screen.getByPlaceholderText("Search memory…"), "zzz");

    expect(await screen.findByText("No files match")).toBeInTheDocument();
  });

  it("shows the failure instead of an empty shelf", async () => {
    vi.mocked(apiClient.get).mockRejectedValue(new ApiError(502, "upstream", null));
    mount();

    expect(await screen.findByRole("alert")).toBeInTheDocument();
  });

  it("lets a viewer add their own personal file but not edit or remove existing ones", async () => {
    mount({ canEdit: false });
    await screen.findByText("user-preferences");

    // A member may seed their own personal memory through the create dialog...
    expect(screen.getByRole("button", { name: "New file" })).toBeInTheDocument();
    // ...but the operator controls over files that already exist stay hidden.
    expect(
      screen.queryByRole("button", { name: "Delete user-preferences" }),
    ).not.toBeInTheDocument();
  });
});
