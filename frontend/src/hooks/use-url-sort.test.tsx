import { act, renderHook } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { useUrlSort } from "./use-url-sort";

const params = { current: new URLSearchParams() };
vi.mock("next/navigation", () => ({ useSearchParams: () => params.current }));

const ALLOWED = ["email", "created_at"] as const;

describe("useUrlSort", () => {
  beforeEach(() => {
    params.current = new URLSearchParams();
    window.history.replaceState({}, "", "/");
  });

  it("starts from the fallback when the URL names no sort", () => {
    const { result } = renderHook(() => useUrlSort(ALLOWED, { by: "created_at", dir: "desc" }));

    expect(result.current.sort).toEqual({ by: "created_at", dir: "desc" });
  });

  it("reads the sort a copied URL carries", () => {
    params.current = new URLSearchParams("sort_by=email&sort_dir=asc");

    const { result } = renderHook(() => useUrlSort(ALLOWED, { by: "created_at", dir: "desc" }));

    expect(result.current.sort).toEqual({ by: "email", dir: "asc" });
  });

  it("falls back when the URL names a column the route cannot sort on", () => {
    params.current = new URLSearchParams("sort_by=password&sort_dir=asc");

    const { result } = renderHook(() => useUrlSort(ALLOWED, { by: "created_at", dir: "desc" }));

    expect(result.current.sort).toEqual({ by: "created_at", dir: "desc" });
  });

  it("treats a mangled direction as descending", () => {
    params.current = new URLSearchParams("sort_by=email&sort_dir=sideways");

    const { result } = renderHook(() => useUrlSort(ALLOWED, { by: "created_at", dir: "desc" }));

    expect(result.current.sort).toEqual({ by: "email", dir: "desc" });
  });

  it("mirrors a new sort into the URL so it can be sent to somebody", () => {
    const { result } = renderHook(() => useUrlSort(ALLOWED, { by: "created_at", dir: "desc" }));

    act(() => result.current.setSort({ by: "email", dir: "asc" }));

    expect(result.current.sort).toEqual({ by: "email", dir: "asc" });
    const search = new URLSearchParams(window.location.search);
    expect(search.get("sort_by")).toBe("email");
    expect(search.get("sort_dir")).toBe("asc");
  });

  it("drops a sort on a column outside the whitelist instead of requesting it", () => {
    const { result } = renderHook(() => useUrlSort(ALLOWED, { by: "created_at", dir: "desc" }));

    act(() => result.current.setSort({ by: "password", dir: "asc" }));

    expect(result.current.sort).toEqual({ by: "created_at", dir: "desc" });
    expect(new URLSearchParams(window.location.search).get("sort_by")).toBeNull();
  });
});
