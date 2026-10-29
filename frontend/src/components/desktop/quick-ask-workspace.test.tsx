import { useEffect, useState } from "react";
import { act, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, expect, it, vi } from "vitest";
import { QuickAskWorkspace } from "./quick-ask-workspace";
import { useAgentSelectionStore, useAuthStore } from "@/stores";
import type { QuickAsk } from "./quick-ask";
const env = vi.hoisted(() => ({
  window: vi.fn(async () => {}),
  tenant: "org",
  loading: false,
  failed: false,
}));
vi.mock("@/hooks/use-organizations", () => ({ useTenantId: () => env.tenant }));
vi.mock("@/lib/desktop/commands", () => ({ newQuickAskWindow: env.window }));
vi.mock("@/lib/desktop/shell", async () => ({
  ...(await vi.importActual<typeof import("@/lib/desktop/shell")>("@/lib/desktop/shell")),
  reportShellFailure: vi.fn(),
}));
vi.mock("./quick-ask-history", () => ({
  RestoreQuickAsk: ({ id }: { id: string }) => <p>{id}</p>,
  useQuickAskHistory: () => ({
    isPending: env.loading,
    isError: env.failed,
    refetch: vi.fn(),
    data: {
      items: [{ id: "saved", title: "Saved conversation", agents: [{ id: "history-agent" }] }],
    },
  }),
}));
vi.mock("./quick-ask", () => ({
  QuickAsk: ({
    toolbar,
    onNewConversation,
    onTabState,
    initialConversationId,
    historyControl,
  }: NonNullable<Parameters<typeof QuickAsk>[0]>) => {
    const [draft, setDraft] = useState("");
    const [files, setFiles] = useState(0);
    const agent = useAgentSelectionStore((s) => s.selectedAgentId);
    const select = useAgentSelectionStore((s) => s.select);
    useEffect(() => {
      onTabState?.({
        conversationId: initialConversationId ?? null,
        title: draft || "New chat",
        processing: false,
        agentId: agent,
      });
    }, [draft, initialConversationId, agent, onTabState]);
    return (
      <div>
        {toolbar}
        {historyControl}
        <textarea aria-label="Draft" value={draft} onChange={(e) => setDraft(e.target.value)} />
        <button onClick={() => setFiles((n) => n + 1)}>Attach {files}</button>
        <button onClick={() => select("changed-agent")}>{agent || "default"}</button>
        <button onClick={onNewConversation}>New conversation</button>
      </div>
    );
  },
}));
beforeEach(() => {
  env.window.mockClear();
  env.tenant = "org";
  env.loading = false;
  env.failed = false;
  useAuthStore.setState({
    user: { id: "alice", email: "alice@example.com", is_active: true, created_at: "2026-10-01" },
  });
  useAgentSelectionStore.getState().select("initial-agent");
});
it("preserves separate drafts, attachments and agent selections when switching tabs", async () => {
  const user = userEvent.setup();
  render(<QuickAskWorkspace />);
  await user.type(screen.getByRole("textbox", { name: "Draft" }), "first draft");
  await user.click(screen.getByRole("button", { name: "Attach 0" }));
  await user.click(screen.getByRole("button", { name: "initial-agent" }));
  await user.click(screen.getByRole("button", { name: "New tab" }));
  expect(screen.getByRole("textbox", { name: "Draft" })).toHaveValue("");
  expect(screen.getByRole("button", { name: "Attach 0" })).toBeVisible();
  await user.type(screen.getByRole("textbox", { name: "Draft" }), "second draft");
  await user.click(screen.getByRole("tab", { name: "first draft" }));
  expect(screen.getByRole("textbox", { name: "Draft" })).toHaveValue("first draft");
  expect(screen.getByRole("button", { name: "Attach 1" })).toBeVisible();
  expect(screen.getByRole("button", { name: "changed-agent" })).toBeVisible();
  expect(useAgentSelectionStore.getState().selectedAgentId).toBe("initial-agent");
});
it("opens saved conversations once and can request a separate native window", async () => {
  const user = userEvent.setup();
  render(<QuickAskWorkspace />);
  await user.click(screen.getByRole("button", { name: "Recent conversations" }));
  await user.click(screen.getByRole("button", { name: "Saved conversation" }));
  expect(screen.getByText("saved")).toBeVisible();
  expect(screen.getAllByRole("tab")).toHaveLength(2);
  await user.click(screen.getByRole("button", { name: "Recent conversations" }));
  await user.click(screen.getByRole("button", { name: "Saved conversation" }));
  expect(screen.getAllByRole("tab")).toHaveLength(2);
  await user.click(screen.getByRole("button", { name: "New window" }));
  expect(env.window).toHaveBeenCalledOnce();
});
it("supports keyboard tab navigation and closing the final tab leaves a fresh draft", async () => {
  const user = userEvent.setup();
  render(<QuickAskWorkspace />);
  await user.type(screen.getByRole("textbox", { name: "Draft" }), "one");
  await user.click(screen.getByRole("button", { name: "New tab" }));
  screen.getAllByRole("tab")[1]?.focus();
  await user.keyboard("{ArrowLeft}");
  expect(screen.getByRole("tab", { name: "one" })).toHaveAttribute("aria-selected", "true");
  await user.click(screen.getByRole("button", { name: "Close tab: one" }));
  expect(screen.getAllByRole("tab")).toHaveLength(1);
  await user.click(screen.getByRole("button", { name: "Close tab: New chat" }));
  expect(screen.getAllByRole("tab")).toHaveLength(1);
  expect(screen.getByRole("textbox", { name: "Draft" })).toHaveValue("");
});
it("drops the previous account's workspace on account or organization changes", async () => {
  const user = userEvent.setup();
  const view = render(<QuickAskWorkspace />);
  await user.type(screen.getByRole("textbox", { name: "Draft" }), "private draft");
  env.tenant = "other-org";
  view.rerender(<QuickAskWorkspace />);
  expect(screen.getByRole("textbox", { name: "Draft" })).toHaveValue("");
  await user.type(screen.getByRole("textbox", { name: "Draft" }), "another private draft");
  act(() =>
    useAuthStore.setState({
      user: { id: "bob", email: "bob@example.com", is_active: true, created_at: "2026-10-01" },
    }),
  );
  expect(screen.getByRole("textbox", { name: "Draft" })).toHaveValue("");
});
it("shows loading and retry states in history", async () => {
  env.loading = true;
  const user = userEvent.setup();
  const view = render(<QuickAskWorkspace />);
  await user.click(screen.getByRole("button", { name: "Recent conversations" }));
  expect(screen.getByText("Loading conversations…")).toBeVisible();
  env.loading = false;
  env.failed = true;
  view.rerender(<QuickAskWorkspace />);
  expect(screen.getByRole("button", { name: /Could not load conversations/ })).toBeVisible();
});
