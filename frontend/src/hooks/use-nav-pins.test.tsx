import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { useNavPins } from "./use-nav-pins";
import * as api from "@/lib/nav-pins-api";
import { qk } from "@/lib/query-keys";
import { useOrgStore } from "@/stores";

vi.mock("@/lib/nav-pins-api", () => ({ getNavPins: vi.fn(), putNavPins: vi.fn() }));

const client = new QueryClient({
  defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
});

function wrapper({ children }: { children: ReactNode }) {
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

async function hook(saved: string[]) {
  vi.mocked(api.getNavPins).mockResolvedValue({ item_ids: saved });
  const rendered = renderHook(() => useNavPins(), { wrapper });
  await waitFor(() => expect(rendered.result.current.ready).toBe(true));
  expect(rendered.result.current.pinnedIds).toEqual(saved);
  return rendered.result;
}

beforeEach(() => {
  vi.clearAllMocks();
  client.clear();
  useOrgStore.setState({ activeOrgId: "org1" });
});

describe("useNavPins", () => {
  it("reads nothing pinned as an empty list", async () => {
    const result = await hook([]);
    expect(result.current.pinnedIds).toEqual([]);
  });

  it("pins by appending and saves the whole ordered list", async () => {
    vi.mocked(api.putNavPins).mockResolvedValue({ item_ids: ["agents", "skills"] });
    const result = await hook(["agents"]);

    act(() => result.current.toggle("skills"));

    await waitFor(() => expect(result.current.pinnedIds).toEqual(["agents", "skills"]));
    await waitFor(() => expect(api.putNavPins).toHaveBeenCalledWith(["agents", "skills"]));
  });

  it("unpins a pinned entry", async () => {
    vi.mocked(api.putNavPins).mockResolvedValue({ item_ids: [] });
    const result = await hook(["agents"]);

    act(() => result.current.toggle("agents"));

    await waitFor(() => expect(result.current.pinnedIds).toEqual([]));
    expect(api.putNavPins).toHaveBeenCalledWith([]);
  });

  it("stays not ready and refuses clicks before the first read arrives", () => {
    vi.mocked(api.getNavPins).mockReturnValue(new Promise(() => {}));
    const { result } = renderHook(() => useNavPins(), { wrapper });

    expect(result.current.ready).toBe(false);
    act(() => result.current.toggle("skills"));

    expect(api.putNavPins).not.toHaveBeenCalled();
  });

  it("never replaces saved pins with a one-item list after a failed read", async () => {
    vi.mocked(api.getNavPins).mockRejectedValue(new Error("offline"));
    const { result } = renderHook(() => useNavPins(), { wrapper });
    await waitFor(() => expect(client.getQueryState(qk.nav.pins("org1"))?.status).toBe("error"));

    act(() => result.current.toggle("skills"));

    expect(result.current.ready).toBe(false);
    expect(api.putNavPins).not.toHaveBeenCalled();
  });

  it("rolls the column back when the save fails", async () => {
    vi.mocked(api.putNavPins).mockRejectedValue(new Error("boom"));
    const result = await hook(["agents"]);

    act(() => result.current.toggle("skills"));

    await waitFor(() => expect(api.putNavPins).toHaveBeenCalled());
    await waitFor(() => expect(result.current.pinnedIds).toEqual(["agents"]));
  });

  it("keeps each organization's pins under its own key", async () => {
    vi.mocked(api.putNavPins).mockResolvedValue({ item_ids: ["skills"] });
    const result = await hook([]);

    act(() => result.current.toggle("skills"));
    await waitFor(() => expect(result.current.pinnedIds).toEqual(["skills"]));

    expect(client.getQueryData(qk.nav.pins("org1"))).toEqual({ item_ids: ["skills"] });
    expect(client.getQueryData(qk.nav.pins("org2"))).toBeUndefined();
  });

  it("reads the current organization's pins when none is chosen yet", async () => {
    useOrgStore.setState({ activeOrgId: null });
    vi.mocked(api.getNavPins).mockResolvedValue({ item_ids: ["agents"] });
    const { result } = renderHook(() => useNavPins(), { wrapper });

    await waitFor(() => expect(result.current.pinnedIds).toEqual(["agents"]));
    expect(client.getQueryData(qk.nav.pins("current"))).toEqual({ item_ids: ["agents"] });
  });

  describe("saves in a row", () => {
    function deferred<T>() {
      let resolve!: (value: T) => void;
      let reject!: (error: Error) => void;
      const promise = new Promise<T>((ok, no) => {
        resolve = ok;
        reject = no;
      });
      return { promise, resolve, reject };
    }

    it("runs one save at a time and builds the second list from the first's answer", async () => {
      const first = deferred<api.NavPins>();
      vi.mocked(api.putNavPins)
        .mockReturnValueOnce(first.promise)
        .mockResolvedValueOnce({ item_ids: ["agents", "skills"] });
      const result = await hook([]);

      act(() => result.current.toggle("agents"));
      act(() => result.current.toggle("skills"));
      await waitFor(() => expect(result.current.pinnedIds).toEqual(["agents", "skills"]));
      expect(api.putNavPins).toHaveBeenCalledTimes(1);

      await act(async () => first.resolve({ item_ids: ["agents"] }));

      await waitFor(() => expect(api.putNavPins).toHaveBeenCalledTimes(2));
      expect(api.putNavPins).toHaveBeenLastCalledWith(["agents", "skills"]);
      await waitFor(() => expect(result.current.pinnedIds).toEqual(["agents", "skills"]));
    });

    it("ignores an older save's late answer while a newer click is pending", async () => {
      const first = deferred<api.NavPins>();
      const second = deferred<api.NavPins>();
      vi.mocked(api.putNavPins)
        .mockReturnValueOnce(first.promise)
        .mockReturnValueOnce(second.promise);
      const result = await hook([]);

      act(() => result.current.toggle("agents"));
      act(() => result.current.toggle("skills"));
      await act(async () => first.resolve({ item_ids: ["agents"] }));
      await waitFor(() => expect(api.putNavPins).toHaveBeenCalledTimes(2));

      expect(result.current.pinnedIds).toEqual(["agents", "skills"]);
      await act(async () => second.resolve({ item_ids: ["agents", "skills"] }));
      await waitFor(() => expect(result.current.pinnedIds).toEqual(["agents", "skills"]));
    });

    it("does not roll back a newer click when an older save fails", async () => {
      const first = deferred<api.NavPins>();
      vi.mocked(api.putNavPins)
        .mockReturnValueOnce(first.promise)
        .mockResolvedValueOnce({ item_ids: ["skills"] });
      const result = await hook([]);

      act(() => result.current.toggle("agents"));
      act(() => result.current.toggle("skills"));
      await act(async () => first.reject(new Error("boom")));

      // The second save is built from what the server confirmed, not from the failed click.
      await waitFor(() => expect(api.putNavPins).toHaveBeenLastCalledWith(["skills"]));
      await waitFor(() => expect(result.current.pinnedIds).toEqual(["skills"]));
    });

    it("rolls back to the confirmed list when the newest save fails", async () => {
      vi.mocked(api.putNavPins).mockResolvedValueOnce({ item_ids: ["agents"] });
      vi.mocked(api.putNavPins).mockRejectedValueOnce(new Error("boom"));
      const result = await hook([]);

      act(() => result.current.toggle("agents"));
      await waitFor(() => expect(result.current.pinnedIds).toEqual(["agents"]));
      act(() => result.current.toggle("skills"));

      await waitFor(() => expect(api.putNavPins).toHaveBeenCalledTimes(2));
      await waitFor(() => expect(result.current.pinnedIds).toEqual(["agents"]));
    });

    it("keeps both pins when a read in flight answers late after two clicks", async () => {
      const late = deferred<api.NavPins>();
      vi.mocked(api.putNavPins)
        .mockResolvedValueOnce({ item_ids: ["agents"] })
        .mockResolvedValueOnce({ item_ids: ["agents", "skills"] });
      const result = await hook([]);
      vi.mocked(api.getNavPins).mockReturnValueOnce(late.promise);
      void client.refetchQueries({ queryKey: qk.nav.pins("org1") });

      act(() => result.current.toggle("agents"));
      act(() => result.current.toggle("skills"));
      await act(async () => late.resolve({ item_ids: [] }));

      await waitFor(() => expect(api.putNavPins).toHaveBeenCalledTimes(2));
      expect(api.putNavPins).toHaveBeenLastCalledWith(["agents", "skills"]);
      await waitFor(() => expect(result.current.pinnedIds).toEqual(["agents", "skills"]));
    });

    it("keeps both pins when a read that started during a save answers with the old list", async () => {
      const first = deferred<api.NavPins>();
      const read = deferred<api.NavPins>();
      vi.mocked(api.putNavPins)
        .mockReturnValueOnce(first.promise)
        .mockResolvedValueOnce({ item_ids: ["agents", "skills"] });
      const result = await hook([]);

      act(() => result.current.toggle("agents"));
      act(() => result.current.toggle("skills"));
      await waitFor(() => expect(result.current.pinnedIds).toEqual(["agents", "skills"]));
      vi.mocked(api.getNavPins).mockReturnValueOnce(read.promise);
      void client.refetchQueries({ queryKey: qk.nav.pins("org1") });
      await waitFor(() => expect(api.getNavPins).toHaveBeenCalledTimes(2));

      await act(async () => read.resolve({ item_ids: [] }));
      expect(result.current.pinnedIds).toEqual(["agents", "skills"]);
      await act(async () => first.resolve({ item_ids: ["agents"] }));

      await waitFor(() => expect(api.putNavPins).toHaveBeenLastCalledWith(["agents", "skills"]));
      await waitFor(() => expect(result.current.pinnedIds).toEqual(["agents", "skills"]));
    });

    describe("a read that cannot be trusted, with nothing cached yet", () => {
      function otherTab() {
        const other = new QueryClient({
          defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
        });
        const wrap = ({ children }: { children: ReactNode }) => (
          <QueryClientProvider client={other}>{children}</QueryClientProvider>
        );
        return renderHook(() => useNavPins(), { wrapper: wrap });
      }

      it("does not rewrite what the server confirmed when it began during a save", async () => {
        const first = deferred<api.NavPins>();
        const read = deferred<api.NavPins>();
        vi.mocked(api.putNavPins)
          .mockReturnValueOnce(first.promise)
          .mockResolvedValueOnce({ item_ids: ["agents", "routines"] });
        const result = await hook(["agents"]);
        act(() => result.current.toggle("skills"));
        await waitFor(() => expect(api.putNavPins).toHaveBeenCalledTimes(1));

        vi.mocked(api.getNavPins).mockReturnValueOnce(read.promise);
        const tab = otherTab();
        await waitFor(() => expect(api.getNavPins).toHaveBeenCalledTimes(2));
        await act(async () => read.resolve({ item_ids: [] }));
        act(() => result.current.toggle("routines"));
        await act(async () => first.reject(new Error("boom")));

        // Built from what was confirmed before the failed save: `agents` is still there.
        await waitFor(() =>
          expect(api.putNavPins).toHaveBeenLastCalledWith(["agents", "routines"]),
        );
        tab.unmount();
      });

      it("does not rewrite what the server confirmed when it was cancelled", async () => {
        const read = deferred<api.NavPins>();
        vi.mocked(api.putNavPins).mockResolvedValue({ item_ids: ["agents", "routines"] });
        const result = await hook(["agents"]);

        vi.mocked(api.getNavPins).mockReturnValueOnce(read.promise);
        const tab = otherTab();
        await waitFor(() => expect(api.getNavPins).toHaveBeenCalledTimes(2));
        tab.unmount();
        await act(async () => read.resolve({ item_ids: ["skills"] }));
        act(() => result.current.toggle("routines"));

        await waitFor(() =>
          expect(api.putNavPins).toHaveBeenLastCalledWith(["agents", "routines"]),
        );
      });
    });

    it("passes the read's abort signal to the request", async () => {
      await hook([]);
      expect(vi.mocked(api.getNavPins).mock.calls[0]?.[0]).toBeInstanceOf(AbortSignal);
    });

    it("keeps a click when a read that was in flight answers late with the old list", async () => {
      const late = deferred<api.NavPins>();
      vi.mocked(api.putNavPins).mockResolvedValue({ item_ids: ["skills"] });
      const result = await hook([]);
      vi.mocked(api.getNavPins).mockReturnValueOnce(late.promise);
      void client.refetchQueries({ queryKey: qk.nav.pins("org1") });

      act(() => result.current.toggle("skills"));
      await act(async () => late.resolve({ item_ids: [] }));

      await waitFor(() => expect(api.putNavPins).toHaveBeenCalledWith(["skills"]));
      await waitFor(() => expect(result.current.pinnedIds).toEqual(["skills"]));
    });
  });
});
