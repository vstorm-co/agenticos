import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, expect, it, vi } from "vitest";

import { useAgentSelectionStore, useConversationStore } from "@/stores";
import { useChatControlsStore } from "@/stores/chat-controls-store";
import { useWorkOnStore } from "@/stores/work-on-store";
import type { LocalGrant, LocalMode } from "@/lib/desktop/commands";
import { LocalCodingControl } from "./local-coding-control";

vi.mock("@/hooks/use-agents", () => ({ useAgents: () => ({ agents: env.published }) }));

const env = vi.hoisted(() => ({
  published: [] as {
    id: string;
    local_coding_agent: { harness: "claude_code" | "codex"; access: "edit" | "read_only" };
  }[],
  linked: true,
  link: vi.fn(),
  grants: [] as LocalGrant[],
  pick: vi.fn<(mode: LocalMode) => Promise<LocalGrant | null>>(),
  revoke: vi.fn(),
}));
vi.mock("@/hooks/use-desktop", () => ({
  useDeviceStatus: () => ({ data: { linked: env.linked } }),
  useDeviceLink: () => ({ link: { mutateAsync: env.link } }),
  useLocalAgents: () => ({ state: { data: [] } }),
  useLocalFolders: () => ({ pick: { mutateAsync: env.pick } }),
}));
vi.mock("@/lib/desktop/commands", async (original) => ({
  ...(await original<typeof import("@/lib/desktop/commands")>()),
  getLocalState: async () => ({ grants: env.grants }),
  revokeWholeComputer: env.revoke,
}));
function view() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <LocalCodingControl />
    </QueryClientProvider>,
  );
}
const folder = { path: "/approved", mode: "full_access" } as const;
beforeEach(() => {
  env.linked = true;
  env.published = [];
  useAgentSelectionStore.setState({ selectedAgentId: null });
  env.grants = [];
  env.link.mockReset();
  env.pick.mockReset().mockResolvedValue(folder);
  env.revoke.mockReset();
  useChatControlsStore.setState({ byScope: {} });
  useConversationStore.setState({ currentConversationId: "coding-chat" });
  useWorkOnStore.setState({ byConversation: {}, codingByConversation: {}, draftCoding: null });
});
it("sets up a full-access folder automatically before enabling the coding harness", async () => {
  const user = userEvent.setup();
  view();
  await user.click(screen.getByRole("radio", { name: "Codex" }));
  await waitFor(() => expect(useWorkOnStore.getState().codingFor("coding-chat")).toBe("codex"));
  expect(env.pick).toHaveBeenCalledWith("full_access");
  expect(useWorkOnStore.getState().targetFor("coding-chat")).toMatchObject({
    folder: folder.path,
    mode: folder.mode,
  });
  expect(useWorkOnStore.getState().codingFor("another-chat")).toBeNull();
  await user.click(screen.getByRole("radio", { name: "Use agent setting" }));
  await waitFor(() => expect(useWorkOnStore.getState().codingFor("coding-chat")).toBeNull());
});
it("requires successful pairing before choosing a folder", async () => {
  env.linked = false;
  env.link.mockResolvedValue({ linked: false });
  view();
  await userEvent.click(screen.getByRole("radio", { name: "Claude Code" }));
  await waitFor(() => expect(env.link).toHaveBeenCalledOnce());
  expect(env.pick).not.toHaveBeenCalled();
  expect(useWorkOnStore.getState().codingFor("coding-chat")).toBeNull();
});
it("reuses a real native full-access grant and enables local files in that mode", async () => {
  env.grants = [folder];
  useWorkOnStore.getState().set("coding-chat", { folder: folder.path, mode: "workspace_write" });
  view();
  await userEvent.click(screen.getByRole("radio", { name: "Claude Code" }));
  await waitFor(() =>
    expect(useWorkOnStore.getState().codingFor("coding-chat")).toBe("claude_code"),
  );
  expect(env.pick).not.toHaveBeenCalled();
  expect(useWorkOnStore.getState().targetFor("coding-chat")?.mode).toBe("full_access");
});
it("does not trust a stale full-access selection without its native grant", async () => {
  useWorkOnStore.getState().set("coding-chat", { folder: "/old", mode: "full_access" });
  view();
  await userEvent.click(screen.getByRole("radio", { name: "Codex" }));
  await waitFor(() =>
    expect(useWorkOnStore.getState().targetFor("coding-chat")?.folder).toBe(folder.path),
  );
  expect(env.pick).toHaveBeenCalledOnce();
});
it("keeps the previous setting when the person cancels the folder picker", async () => {
  env.pick.mockResolvedValue(null);
  view();
  await userEvent.click(screen.getByRole("radio", { name: "Codex" }));
  await waitFor(() => expect(env.pick).toHaveBeenCalledOnce());
  expect(useWorkOnStore.getState().codingFor("coding-chat")).toBeNull();
  expect(useWorkOnStore.getState().targetFor("coding-chat")).toBeNull();
});
it("replaces whole-computer consent with a folder grant after explicit folder selection", async () => {
  useWorkOnStore
    .getState()
    .set("coding-chat", { folder: "/home", mode: "full_access", computer_grant: "whole" });
  view();
  await userEvent.click(screen.getByRole("radio", { name: "Claude Code" }));
  await waitFor(() =>
    expect(useWorkOnStore.getState().codingFor("coding-chat")).toBe("claude_code"),
  );
  expect(env.revoke).toHaveBeenCalledWith("whole");
  expect(useWorkOnStore.getState().targetFor("coding-chat")?.computer_grant).toBeUndefined();
});

it("asks for full access when the native folder grant only permits workspace writes", async () => {
  env.grants = [{ path: "/approved", mode: "workspace_write" }];
  useWorkOnStore.getState().set("coding-chat", { folder: "/approved", mode: "workspace_write" });
  view();
  await userEvent.click(screen.getByRole("radio", { name: "Claude Code" }));
  await waitFor(() => expect(env.pick).toHaveBeenCalledWith("full_access"));
  await waitFor(() =>
    expect(useWorkOnStore.getState().codingFor("coding-chat")).toBe("claude_code"),
  );
});

it("preserves whole-computer consent when the person cancels the folder picker", async () => {
  const original = { folder: "/home", mode: "full_access", computer_grant: "whole" } as const;
  useWorkOnStore.getState().set("coding-chat", original);
  env.pick.mockResolvedValue(null);
  view();
  await userEvent.click(screen.getByRole("radio", { name: "Codex" }));
  await waitFor(() => expect(env.pick).toHaveBeenCalledOnce());
  expect(env.revoke).not.toHaveBeenCalled();
  expect(useWorkOnStore.getState().targetFor("coding-chat")).toEqual(original);
});

it("offers folder setup for the published local harness even without a chat override", async () => {
  env.published = [
    { id: "local", local_coding_agent: { harness: "claude_code", access: "read_only" } },
  ];
  useAgentSelectionStore.setState({ selectedAgentId: "local" });
  view();
  expect(screen.getByRole("radio", { name: "Agent setting · Claude Code" })).toBeInTheDocument();
  await userEvent.click(screen.getByRole("button", { name: "Choose a folder" }));
  await waitFor(() =>
    expect(useWorkOnStore.getState().codingFor("coding-chat")).toBe("claude_code"),
  );
  expect(env.pick).toHaveBeenCalledWith("full_access");
});
