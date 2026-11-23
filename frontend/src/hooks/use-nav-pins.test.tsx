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
  await waitFor(() => expect(rendered.result.current.pinnedIds).toEqual(saved));
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

  it("starts from nothing before the first read arrives", async () => {
    vi.mocked(api.getNavPins).mockReturnValue(new Promise(() => {}));
    vi.mocked(api.putNavPins).mockResolvedValue({ item_ids: ["skills"] });
    const { result } = renderHook(() => useNavPins(), { wrapper });

    act(() => result.current.toggle("skills"));

    await waitFor(() => expect(api.putNavPins).toHaveBeenCalledWith(["skills"]));
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
});
