import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, renderHook, waitFor } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";
import type { ReactNode } from "react";
import { useNotificationRoutes } from "./use-notification-routes";
import * as api from "@/lib/notification-preferences-api";
import { qk } from "@/lib/query-keys";
import { useOrgStore } from "@/stores/org-store";

vi.mock("@/lib/notification-preferences-api", () => ({
  listNotificationRoutes: vi.fn(),
  replaceNotificationRoute: vi.fn(),
}));
const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
function wrapper({ children }: { children: ReactNode }) {
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}
beforeEach(() => {
  client.clear();
  vi.clearAllMocks();
  useOrgStore.setState({ activeOrgId: "org-one" });
  vi.mocked(api.listNotificationRoutes).mockResolvedValue({ items: [], destinations: [] });
});

it("requires an active organization before reading destinations", async () => {
  useOrgStore.setState({ activeOrgId: null });
  const { result } = renderHook(() => useNotificationRoutes(), { wrapper });
  expect(result.current.isLoading).toBe(true);
  expect(api.listNotificationRoutes).not.toHaveBeenCalled();
  act(() => useOrgStore.setState({ activeOrgId: "org-one" }));
  await waitFor(() => expect(result.current.isLoading).toBe(false));
  expect(api.listNotificationRoutes).toHaveBeenCalledOnce();
});

it("does not expose cached destinations from the previous organization", async () => {
  client.setQueryData(qk.notifications.destinations("org-one"), {
    items: [{ id: "one" }],
    destinations: [],
  });
  const { result } = renderHook(() => useNotificationRoutes(), { wrapper });
  expect(result.current.data?.items[0]?.id).toBe("one");
  act(() => useOrgStore.setState({ activeOrgId: "org-two" }));
  expect(result.current.data?.items[0]?.id).not.toBe("one");
  await waitFor(() => expect(result.current.data?.items).toEqual([]));
});

it("refreshes the server's current routing after a successful replacement", async () => {
  vi.mocked(api.replaceNotificationRoute).mockResolvedValue({ items: [], destinations: [] });
  const { result } = renderHook(() => useNotificationRoutes(), { wrapper });
  await waitFor(() => expect(result.current.isLoading).toBe(false));
  await act(async () => {
    await result.current.replace({ channel: "sms", session_id: null });
  });
  expect(api.replaceNotificationRoute).toHaveBeenCalledWith(
    { channel: "sms", session_id: null },
    expect.anything(),
  );
  await waitFor(() => expect(api.listNotificationRoutes).toHaveBeenCalledTimes(2));
});
