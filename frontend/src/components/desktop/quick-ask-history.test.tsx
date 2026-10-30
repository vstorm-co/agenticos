import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, render, renderHook, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, expect, it, vi } from "vitest";
import type { ReactNode } from "react";
import { RestoreQuickAsk, useQuickAskHistory } from "./quick-ask-history";
import { useCurrentRelease } from "@/hooks/use-current-release";
import { useDesktopActiveRuns } from "@/hooks/use-desktop-active-runs";
import { useChatStore, useConversationStore } from "@/stores";
import { apiClient } from "@/lib/api-client";
const env = vi.hoisted(() => ({
  select: vi.fn(),
  earlier: vi.fn(),
  loading: false,
  error: null as Error | null,
  more: false,
  loadingEarlier: false,
  runs: vi.fn(),
}));
vi.mock("@/hooks/use-conversations", () => ({
  useConversations: () => ({
    selectConversation: env.select,
    isLoading: env.loading,
    error: env.error,
    hasEarlierMessages: env.more,
    isLoadingEarlier: env.loadingEarlier,
    loadEarlierMessages: env.earlier,
  }),
}));
vi.mock("@/hooks/use-organizations", () => ({ useTenantId: () => "org" }));
vi.mock("@/hooks/use-permissions", () => ({ usePermissions: () => ({ can: () => true }) }));
vi.mock("@/hooks/use-runs", () => ({ useRuns: env.runs }));
vi.mock("@/lib/api-client", () => ({ apiClient: { get: vi.fn() } }));
const wrapper = ({ children }: { children: ReactNode }) => (
  <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
    {children}
  </QueryClientProvider>
);
beforeEach(() => {
  vi.clearAllMocks();
  env.loading = false;
  env.error = null;
  env.more = false;
  env.loadingEarlier = false;
  useConversationStore.setState({ currentMessages: [] });
  vi.mocked(apiClient.get).mockResolvedValue({ items: [] });
  env.select.mockResolvedValue(undefined);
  env.earlier.mockResolvedValue(undefined);
});
it("queries history and installed release only when enabled, including trimmed search", async () => {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const provider = ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={client}>{children}</QueryClientProvider>
  );
  const { result, rerender } = renderHook(
    ({ enabled, search }) => ({
      history: useQuickAskHistory(search, enabled),
      release: useCurrentRelease(enabled),
    }),
    { initialProps: { enabled: false, search: "" }, wrapper: provider },
  );
  expect(apiClient.get).not.toHaveBeenCalled();
  rerender({ enabled: true, search: "  invoice  " });
  await waitFor(() =>
    expect(result.current.history.isSuccess && result.current.release.isSuccess).toBe(true),
  );
  expect(apiClient.get).toHaveBeenCalledWith("/releases/current");
  expect(apiClient.get).toHaveBeenCalledWith(expect.stringContaining("search=invoice"));
  rerender({ enabled: true, search: "" });
  await waitFor(() =>
    expect(apiClient.get).toHaveBeenCalledWith(
      "/conversations?limit=50&sort_by=updated_at&sort_dir=desc&hide_api=true",
    ),
  );
});
it("restores only the requested conversation and supports retry and earlier pages", async () => {
  const reread = vi.fn();
  useChatStore.setState({ rereadMessages: reread });
  const user = userEvent.setup();
  const view = render(<RestoreQuickAsk id="c" />, { wrapper });
  expect(env.select).toHaveBeenCalledWith("c");
  expect(reread).not.toHaveBeenCalled();
  act(() =>
    useConversationStore.setState({
      currentMessages: [
        { id: "m", conversation_id: "other", role: "user", content: "private", created_at: "now" },
      ],
    }),
  );
  expect(reread).not.toHaveBeenCalled();
  act(() =>
    useConversationStore.setState({
      currentMessages: [
        { id: "m", conversation_id: "c", role: "user", content: "hello", created_at: "now" },
      ],
    }),
  );
  expect(reread).toHaveBeenCalledWith([expect.objectContaining({ content: "hello" })]);
  env.loading = true;
  view.rerender(<RestoreQuickAsk id="c" />);
  expect(screen.getByRole("status")).toHaveTextContent("Loading conversations");
  env.error = new Error("offline");
  view.rerender(<RestoreQuickAsk id="c" />);
  await user.click(screen.getByRole("button", { name: "Could not load conversations. Try again" }));
  expect(env.select).toHaveBeenCalledTimes(2);
  env.error = null;
  env.loading = false;
  env.more = true;
  env.loadingEarlier = true;
  view.rerender(<RestoreQuickAsk id="c" />);
  expect(screen.getByRole("button", { name: "Load earlier messages" })).toBeDisabled();
  env.loadingEarlier = false;
  view.rerender(<RestoreQuickAsk id="c" />);
  await user.click(screen.getByRole("button", { name: "Load earlier messages" }));
  expect(env.earlier).toHaveBeenCalledOnce();
});
it("polls the account's active runs rather than a deployment-wide list", () => {
  renderHook(useDesktopActiveRuns);
  expect(env.runs).toHaveBeenCalledWith(
    undefined,
    expect.objectContaining({
      statuses: ["running", "awaiting_answer", "awaiting_approval"],
      refetchInBackground: true,
      refetchIntervalMs: 5000,
    }),
  );
});
