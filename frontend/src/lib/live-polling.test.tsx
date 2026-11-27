import { QueryClient, QueryClientProvider, focusManager, useQuery } from "@tanstack/react-query";
import { act, renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

import { livePolling, stoppedPolling } from "./live-polling";

let client: QueryClient;

function wrapper({ children }: { children: ReactNode }) {
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

function useRun(read: () => Promise<{ status: string }>) {
  return useQuery({
    queryKey: ["run"],
    queryFn: read,
    ...livePolling(1000, (run: { status: string } | undefined) => run?.status === "running"),
  });
}

beforeEach(() => {
  // As the console's provider sets them: focus alone reads nothing again.
  client = new QueryClient({
    defaultOptions: { queries: { retry: false, refetchOnWindowFocus: false } },
  });
});

afterEach(() => {
  vi.useRealTimers();
  focusManager.setFocused(undefined);
  client.clear();
});

it("reads a moving subject again on the interval and stops when it is still", () => {
  const { refetchInterval } = livePolling(1000, (status: string | undefined) => status === "on");
  expect(refetchInterval({ state: { status: "success", data: "on" } })).toBe(1000);
  expect(refetchInterval({ state: { status: "success", data: "off" } })).toBe(false);
  expect(refetchInterval({ state: { status: "error", data: "on" } })).toBe(false);
});

it("reads again on focus only a query whose last read failed", () => {
  const { refetchOnWindowFocus } = livePolling(1000, () => true);
  expect(refetchOnWindowFocus({ state: { status: "error", data: "on" } })).toBe(true);
  expect(refetchOnWindowFocus({ state: { status: "success", data: "on" } })).toBe(false);
});

it("stops asking after a failed read, and starts again once a retry answers", async () => {
  vi.useFakeTimers({ shouldAdvanceTime: true });
  // An interval reads again only while the page is in view.
  focusManager.setFocused(true);
  const read = vi
    .fn<() => Promise<{ status: string }>>()
    .mockResolvedValueOnce({ status: "running" })
    .mockRejectedValueOnce(new Error("refused"))
    .mockResolvedValue({ status: "running" });
  renderHook(() => useRun(read), { wrapper });
  const query = await waitFor(() => {
    const found = client.getQueryCache().find({ queryKey: ["run"] });
    expect(found?.state.status).toBe("success");
    return found!;
  });

  await act(() => vi.advanceTimersByTimeAsync(1000));
  expect(read).toHaveBeenCalledTimes(2);
  expect(query.state.status).toBe("error");
  expect(query.state.data).toEqual({ status: "running" });
  await act(() => vi.advanceTimersByTimeAsync(5000));
  expect(read).toHaveBeenCalledTimes(2);

  await act(() => query.fetch());
  await act(() => vi.advanceTimersByTimeAsync(1000));
  expect(read).toHaveBeenCalledTimes(4);
});

it("resumes polling when the person comes back to the tab after a failed read", async () => {
  vi.useFakeTimers({ shouldAdvanceTime: true });
  focusManager.setFocused(true);
  const read = vi
    .fn<() => Promise<{ status: string }>>()
    .mockResolvedValueOnce({ status: "running" })
    .mockRejectedValueOnce(new Error("refused"))
    .mockResolvedValue({ status: "running" });
  renderHook(() => useRun(read), { wrapper });
  const query = await waitFor(() => {
    const found = client.getQueryCache().find({ queryKey: ["run"] });
    expect(found?.state.status).toBe("success");
    return found!;
  });
  await act(() => vi.advanceTimersByTimeAsync(1000));
  expect(query.state.status).toBe("error");

  act(() => {
    focusManager.setFocused(false);
    focusManager.setFocused(true);
  });
  await waitFor(() => expect(query.state.status).toBe("success"));
  await act(() => vi.advanceTimersByTimeAsync(1000));
  expect(read).toHaveBeenCalledTimes(4);
});

it("marks a query on screen whose read failed with an older answer kept", async () => {
  const read = vi
    .fn<() => Promise<{ status: string }>>()
    .mockResolvedValueOnce({ status: "running" })
    .mockRejectedValue(new Error("refused"));
  const view = renderHook(() => useRun(read), { wrapper });
  await waitFor(() => expect(view.result.current.isSuccess).toBe(true));
  const query = client.getQueryCache().find({ queryKey: ["run"] })!;
  expect(stoppedPolling(query)).toBe(false);

  await act(() => view.result.current.refetch());
  expect(stoppedPolling(query)).toBe(true);

  view.unmount();
  expect(stoppedPolling(query)).toBe(false);
});

it("leaves alone a failed first read and a query that is not polled", async () => {
  const first = renderHook(() => useRun(() => Promise.reject(new Error("refused"))), { wrapper });
  await waitFor(() => expect(first.result.current.isError).toBe(true));
  expect(stoppedPolling(client.getQueryCache().find({ queryKey: ["run"] })!)).toBe(false);

  const plain = renderHook(
    () =>
      useQuery({
        queryKey: ["plain"],
        queryFn: () => Promise.reject(new Error("refused")),
        initialData: { status: "running" },
        staleTime: 0,
      }),
    { wrapper },
  );
  await act(() => plain.result.current.refetch());
  expect(stoppedPolling(client.getQueryCache().find({ queryKey: ["plain"] })!)).toBe(false);
});
