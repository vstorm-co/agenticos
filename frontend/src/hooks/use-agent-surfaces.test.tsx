import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { toast } from "sonner";

import { useAgentEnvironments } from "./use-agent-environments";
import { useChannelBots } from "./use-channel-bots";
import { useCopyToClipboard } from "./use-copy-to-clipboard";
import { useEmbeds } from "./use-embeds";
import { useMembers } from "./use-members";
import { apiClient } from "@/lib/api-client";

vi.mock("@/lib/api-client", () => ({
  apiClient: { get: vi.fn(), post: vi.fn(), patch: vi.fn(), delete: vi.fn(), upload: vi.fn() },
}));
vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));

function wrapper({ children }: { children: ReactNode }) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(apiClient.get).mockResolvedValue({ items: [], total: 0 });
  vi.mocked(apiClient.post).mockResolvedValue({ id: "x", name: "X", is_active: true });
  vi.mocked(apiClient.patch).mockResolvedValue({ id: "x" });
  vi.mocked(apiClient.delete).mockResolvedValue(undefined);
  vi.mocked(apiClient.upload).mockResolvedValue({ id: "x" });
});

/**
 * The surfaces an agent is reachable through, and the people who can reach it.
 *
 * Four hooks with one thing in common: each is the client half of a permission
 * the server enforces, so every mutation has to surface the refusal rather than
 * do nothing visible. Two carry a rule beyond that - the channel-bot hook does
 * not fetch until the caller says they hold `channels:manage`, and registering a
 * bot invalidates the exposure targets as well as the bot list, because the
 * picker beside it has to offer the new bot without a reload.
 */
describe("an agent's environments", () => {
  it("does not fetch before an agent is chosen", () => {
    renderHook(() => useAgentEnvironments(null), { wrapper });

    expect(apiClient.get).not.toHaveBeenCalled();
  });

  it("reads the environments of one agent", async () => {
    vi.mocked(apiClient.get).mockResolvedValue({
      items: [{ id: "env-1", name: "production" }],
      total: 1,
    });

    const { result } = renderHook(() => useAgentEnvironments("a1"), { wrapper });

    await waitFor(() => expect(result.current.environments).toHaveLength(1));
    expect(apiClient.get).toHaveBeenCalledWith("/agents/a1/environments");
  });

  it("creates an environment", async () => {
    const { result } = renderHook(() => useAgentEnvironments("a1"), { wrapper });

    await result.current.create.mutateAsync({ name: "staging" });

    expect(apiClient.post).toHaveBeenCalledWith("/agents/a1/environments", { name: "staging" });
  });

  it("promotes an environment by moving its pinned version", async () => {
    // Which version answers under a name is the whole of what an environment is.
    const { result } = renderHook(() => useAgentEnvironments("a1"), { wrapper });

    await result.current.promote.mutateAsync({ environmentId: "env-1", versionId: "v2" });

    expect(apiClient.patch).toHaveBeenCalledWith("/agents/a1/environments/env-1", {
      version_id: "v2",
    });
    expect(toast.success).toHaveBeenCalledWith("Promoted");
  });

  it("renames an environment without touching its pin", async () => {
    // The same PATCH as promotion, carrying only the name - sending a
    // version_id here would silently repoint what somebody meant to relabel.
    const { result } = renderHook(() => useAgentEnvironments("a1"), { wrapper });

    await result.current.rename.mutateAsync({ environmentId: "env-1", name: "canary" });

    expect(apiClient.patch).toHaveBeenCalledWith("/agents/a1/environments/env-1", {
      name: "canary",
    });
    expect(toast.success).toHaveBeenCalledWith("Renamed");
  });

  it("removes an environment", async () => {
    const { result } = renderHook(() => useAgentEnvironments("a1"), { wrapper });

    await result.current.remove.mutateAsync("env-1");

    expect(apiClient.delete).toHaveBeenCalledWith("/agents/a1/environments/env-1");
  });

  it("says which action was refused, not just that something was", async () => {
    // Four mutations, four sentences: "failed to promote" and "failed to
    // remove" send somebody to different places.
    const refused = new Error("Missing required permission: agents:publish");
    vi.mocked(apiClient.post).mockRejectedValue(refused);
    vi.mocked(apiClient.patch).mockRejectedValue(refused);
    vi.mocked(apiClient.delete).mockRejectedValue(refused);
    const { result } = renderHook(() => useAgentEnvironments("a1"), { wrapper });

    await expect(result.current.create.mutateAsync({ name: "x" })).rejects.toThrow();
    await expect(
      result.current.promote.mutateAsync({ environmentId: "e", versionId: "v" }),
    ).rejects.toThrow();
    await expect(
      result.current.rename.mutateAsync({ environmentId: "e", name: "x" }),
    ).rejects.toThrow();
    await expect(result.current.remove.mutateAsync("e")).rejects.toThrow();

    expect(vi.mocked(toast.error).mock.calls.flat()).toEqual([
      "Missing required permission: agents:publish",
      "Missing required permission: agents:publish",
      "Missing required permission: agents:publish",
      "Missing required permission: agents:publish",
    ]);
  });
});

describe("an agent's embedded widgets", () => {
  it("does not fetch before an agent is chosen", () => {
    renderHook(() => useEmbeds(null), { wrapper });

    expect(apiClient.get).not.toHaveBeenCalled();
  });

  it("reads the widgets of one agent", async () => {
    vi.mocked(apiClient.get).mockResolvedValue({ items: [{ id: "e-1" }], total: 1 });

    const { result } = renderHook(() => useEmbeds("a1"), { wrapper });

    await waitFor(() => expect(result.current.embeds).toHaveLength(1));
    expect(apiClient.get).toHaveBeenCalledWith("/agents/a1/embeds");
  });

  it("publishes a widget and says where the snippet goes", async () => {
    const { result } = renderHook(() => useEmbeds("a1"), { wrapper });

    await result.current.create.mutateAsync({
      agent_id: "a1",
      allowed_origins: ["https://acme.com"],
    } as Parameters<typeof result.current.create.mutateAsync>[0]);

    expect(apiClient.post).toHaveBeenCalledWith("/agents/embeds", expect.any(Object));
    expect(toast.success).toHaveBeenCalledWith(
      "Widget published. Copy the snippet into your site.",
    );
  });

  it("updates a widget by its own id, not the agent's", async () => {
    const { result } = renderHook(() => useEmbeds("a1"), { wrapper });

    await result.current.update.mutateAsync({ id: "e-1", is_active: false });

    // The id addresses the widget and never travels in the body.
    expect(apiClient.patch).toHaveBeenCalledWith("/agents/embeds/e-1", { is_active: false });
  });

  it("uploads a page's own picture by the embed's id", async () => {
    // A multipart upload rather than a path in the config: the stored path is a
    // column written by this route, because one accepted from a request body
    // would be a caller naming any file the process can open.
    const { result } = renderHook(() => useEmbeds("a1"), { wrapper });
    const file = new File(["x"], "logo.png", { type: "image/png" });

    await result.current.uploadLogo.mutateAsync({ id: "e-1", file });

    expect(apiClient.upload).toHaveBeenCalledWith("/agents/embeds/e-1/logo", file);
    expect(toast.success).toHaveBeenCalledWith("Logo uploaded");
  });

  it("says out loud that removing a widget breaks every page carrying its key", async () => {
    // The key cannot be reissued, so the toast is the last thing standing between
    // somebody and a broken production page.
    const { result } = renderHook(() => useEmbeds("a1"), { wrapper });

    await result.current.remove.mutateAsync("e-1");

    expect(apiClient.delete).toHaveBeenCalledWith("/agents/embeds/e-1");
    expect(toast.success).toHaveBeenCalledWith(
      "Widget removed. Every page carrying its key has stopped working.",
    );
  });

  it("surfaces a refusal on each mutation", async () => {
    const refused = new Error("Missing required permission");
    vi.mocked(apiClient.post).mockRejectedValue(refused);
    vi.mocked(apiClient.patch).mockRejectedValue(refused);
    vi.mocked(apiClient.delete).mockRejectedValue(refused);
    vi.mocked(apiClient.upload).mockRejectedValue(refused);
    const { result } = renderHook(() => useEmbeds("a1"), { wrapper });

    await expect(
      result.current.create.mutateAsync(
        {} as Parameters<typeof result.current.create.mutateAsync>[0],
      ),
    ).rejects.toThrow();
    await expect(result.current.update.mutateAsync({ id: "e" })).rejects.toThrow();
    await expect(result.current.remove.mutateAsync("e")).rejects.toThrow();
    await expect(
      result.current.uploadLogo.mutateAsync({
        id: "e",
        file: new File(["x"], "logo.png", { type: "image/png" }),
      }),
    ).rejects.toThrow();

    expect(toast.error).toHaveBeenCalledTimes(4);
  });
});

describe("the organization's channel bots", () => {
  it("does not fetch for a caller who does not hold the permission", () => {
    // A 403 in the network log on every member's visit to the org page reads as a
    // bug in the page rather than as a permission they do not have.
    renderHook(() => useChannelBots(false), { wrapper });

    expect(apiClient.get).not.toHaveBeenCalled();
  });

  it("reads the bots once the caller is known to hold it", async () => {
    vi.mocked(apiClient.get).mockResolvedValue({ items: [{ id: "b-1" }], total: 1 });

    const { result } = renderHook(() => useChannelBots(true), { wrapper });

    await waitFor(() => expect(result.current.bots).toHaveLength(1));
    expect(apiClient.get).toHaveBeenCalledWith("/channels/bots");
  });

  it("registers a bot and names it in the confirmation", async () => {
    vi.mocked(apiClient.post).mockResolvedValue({ id: "b-1", name: "Acme Support" });
    const { result } = renderHook(() => useChannelBots(true), { wrapper });

    await result.current.create.mutateAsync({
      name: "Acme Support",
      platform: "slack",
    } as Parameters<typeof result.current.create.mutateAsync>[0]);

    expect(apiClient.post).toHaveBeenCalledWith("/channels/bots", expect.any(Object));
    expect(toast.success).toHaveBeenCalledWith(
      "Acme Support registered - agents can now be exposed on it",
    );
  });

  it("activates and deactivates on the endpoint that says which", async () => {
    // Not a PATCH with a flag: the server has two routes, and the toast has to
    // match the one that was called.
    vi.mocked(apiClient.post).mockResolvedValue({ id: "b-1", name: "Acme", is_active: false });
    const { result } = renderHook(() => useChannelBots(true), { wrapper });

    await result.current.setActive.mutateAsync({ botId: "b-1", isActive: false });
    expect(apiClient.post).toHaveBeenCalledWith("/channels/bots/b-1/deactivate", {});
    expect(toast.success).toHaveBeenCalledWith("Acme deactivated");

    vi.mocked(apiClient.post).mockResolvedValue({ id: "b-1", name: "Acme", is_active: true });
    await result.current.setActive.mutateAsync({ botId: "b-1", isActive: true });
    expect(apiClient.post).toHaveBeenCalledWith("/channels/bots/b-1/activate", {});
    expect(toast.success).toHaveBeenCalledWith("Acme activated");
  });

  it("removes a bot", async () => {
    const { result } = renderHook(() => useChannelBots(true), { wrapper });

    await result.current.remove.mutateAsync("b-1");

    expect(apiClient.delete).toHaveBeenCalledWith("/channels/bots/b-1");
    expect(toast.success).toHaveBeenCalledWith("Bot removed");
  });

  it("surfaces a refusal on each mutation", async () => {
    const refused = new Error("Missing required permission: channels:manage");
    vi.mocked(apiClient.post).mockRejectedValue(refused);
    vi.mocked(apiClient.delete).mockRejectedValue(refused);
    const { result } = renderHook(() => useChannelBots(true), { wrapper });

    await expect(
      result.current.create.mutateAsync(
        {} as Parameters<typeof result.current.create.mutateAsync>[0],
      ),
    ).rejects.toThrow();
    await expect(
      result.current.setActive.mutateAsync({ botId: "b", isActive: true }),
    ).rejects.toThrow();
    await expect(result.current.remove.mutateAsync("b")).rejects.toThrow();

    expect(toast.error).toHaveBeenCalledTimes(3);
  });
});

describe("an organization's members", () => {
  it("does not fetch before an organization is chosen", () => {
    renderHook(() => useMembers(""), { wrapper });

    expect(apiClient.get).not.toHaveBeenCalled();
  });

  it("reads the members and the count beside them", async () => {
    // The total is cached with the list rather than derived from it, because a
    // paged response has more members than rows.
    vi.mocked(apiClient.get).mockResolvedValue({
      items: [{ user_id: "u-1", role: "member" }],
      total: 42,
    });

    const { result } = renderHook(() => useMembers("org-1"), { wrapper });

    await waitFor(() => expect(result.current.members).toHaveLength(1));
    expect(result.current.total).toBe(42);
  });

  it("patches a changed role into the cached list", async () => {
    vi.mocked(apiClient.get).mockResolvedValue({
      items: [{ user_id: "u-1", role: "member" }],
      total: 1,
    });
    vi.mocked(apiClient.patch).mockResolvedValue({ user_id: "u-1", role: "admin" });
    const { result } = renderHook(() => useMembers("org-1"), { wrapper });
    await waitFor(() => expect(result.current.members).toHaveLength(1));

    await act(() => result.current.changeRole("u-1", "admin"));

    expect(apiClient.patch).toHaveBeenCalledWith("/orgs/org-1/members/u-1", { role: "admin" });
    await waitFor(() => expect(result.current.members[0]?.role).toBe("admin"));
  });

  it("drops a removed member and the count with them", async () => {
    // Leaving the total behind renders "1 of 2 members" over one row.
    vi.mocked(apiClient.get).mockResolvedValue({
      items: [{ user_id: "u-1" }, { user_id: "u-2" }],
      total: 2,
    });
    const { result } = renderHook(() => useMembers("org-1"), { wrapper });
    await waitFor(() => expect(result.current.members).toHaveLength(2));

    await act(() => result.current.removeMember("u-2"));

    await waitFor(() => expect(result.current.members).toHaveLength(1));
    expect(result.current.total).toBe(1);
  });

  it("reports a refused role change and a refused removal", async () => {
    vi.mocked(apiClient.patch).mockRejectedValue(new Error("nope"));
    vi.mocked(apiClient.delete).mockRejectedValue(new Error("nope"));
    const { result } = renderHook(() => useMembers("org-1"), { wrapper });

    await act(() => result.current.changeRole("u-1", "admin"));
    await act(() => result.current.removeMember("u-1"));

    expect(vi.mocked(toast.error).mock.calls.flat()).toEqual([
      "Failed to update role",
      "Failed to remove member",
    ]);
  });

  it("refetches on demand, and does nothing without an organization", async () => {
    const { result } = renderHook(() => useMembers("org-1"), { wrapper });
    await waitFor(() => expect(apiClient.get).toHaveBeenCalledTimes(1));

    await act(() => {
      result.current.fetchMembers();
      return Promise.resolve();
    });

    await waitFor(() => expect(apiClient.get).toHaveBeenCalledTimes(2));

    const { result: none } = renderHook(() => useMembers(""), { wrapper });
    none.current.fetchMembers();
    expect(apiClient.get).toHaveBeenCalledTimes(2);
  });
});

describe("copying to the clipboard", () => {
  afterEach(() => {
    vi.useRealTimers();
    vi.unstubAllGlobals();
  });

  it("says it copied, then stops saying so", async () => {
    // The confirmation is the whole feedback for a click that changes nothing on
    // screen; leaving it on forever makes the next copy invisible.
    vi.useFakeTimers();
    const writeText = vi.fn().mockResolvedValue(undefined);
    vi.stubGlobal("navigator", { clipboard: { writeText } });
    const { result } = renderHook(() => useCopyToClipboard(1000));

    await act(async () => {
      await result.current.copy("snippet");
    });

    expect(writeText).toHaveBeenCalledWith("snippet");
    expect(result.current.copied).toBe(true);

    await act(async () => {
      vi.advanceTimersByTime(1000);
    });
    expect(result.current.copied).toBe(false);
  });

  it("reports a refused clipboard rather than claiming it copied", async () => {
    // Which is what a page served over plain HTTP, or an unfocused document,
    // answers - and "Copied" there is a lie the reader acts on.
    vi.stubGlobal("navigator", {
      clipboard: { writeText: vi.fn().mockRejectedValue(new Error("denied")) },
    });
    const { result } = renderHook(() => useCopyToClipboard());

    let copied: boolean | undefined;
    await act(async () => {
      copied = await result.current.copy("snippet");
    });

    expect(copied).toBe(false);
    expect(result.current.copied).toBe(false);
  });
});
