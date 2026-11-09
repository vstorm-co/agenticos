import { act, renderHook } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";
import { useWorkOnStore } from "@/stores/work-on-store";
import { useAuthStore } from "@/stores/auth-store";
import { useOrgStore } from "@/stores/org-store";
import { useTurnFileSource } from "./use-turn-file-source";

const env = vi.hoisted(() => ({ desktop: true }));
vi.mock("./use-shell", () => ({ useShell: () => (env.desktop ? { platform: "macos" } : null) }));
beforeEach(() => {
  env.desktop = true;
  useWorkOnStore.setState({ fileRoots: {} });
  useAuthStore.setState({ user: null });
  useOrgStore.setState({ activeOrgId: "org" });
});
it("resolves only a recorded mapping in this account and organization", () => {
  const source = { kind: "local", id: "opaque" } as const;
  const view = renderHook(() => useTurnFileSource(source));
  expect(view.result.current).toBeNull();
  act(() => useWorkOnStore.getState().rememberFileRoot(source.id, "/original"));
  expect(view.result.current).toEqual({ kind: "local", root: "/original" });
  act(() => useWorkOnStore.getState().set(null, { folder: "/other", mode: "full_access" }));
  expect(view.result.current).toEqual({ kind: "local", root: "/original" });
  act(() => useOrgStore.setState({ activeOrgId: "other" }));
  expect(view.result.current).toBeNull();
  act(() => useOrgStore.setState({ activeOrgId: "org" }));
  expect(view.result.current).toEqual({ kind: "local", root: "/original" });
  act(() =>
    useAuthStore.setState({
      user: {
        id: "another-user",
        email: "other@example.com",
        is_active: true,
        created_at: "2026-10-01",
      },
    }),
  );
  expect(view.result.current).toBeNull();
  act(() => useAuthStore.setState({ user: null }));
  env.desktop = false;
  view.rerender();
  expect(view.result.current).toBeNull();
});
it("keeps conversation sources and ignores missing origins", () => {
  const source = { kind: "conversation", id: "chat" } as const;
  expect(renderHook(() => useTurnFileSource(source)).result.current).toEqual(source);
  expect(renderHook(() => useTurnFileSource(undefined)).result.current).toBeNull();
});
