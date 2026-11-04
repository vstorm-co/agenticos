import { act, renderHook } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";
import { projectFolderKey, useProjectFoldersStore } from "@/stores/project-folders-store";
import { useProjectFolder } from "./use-project-folder";
let actor: { user: { id: string } | null } = { user: { id: "alice" } };
let organization: string | null = "org";
vi.mock("@/stores", () => ({
  useAuthStore: (selector: (state: typeof actor) => unknown) => selector(actor),
}));
vi.mock("@/hooks/use-organizations", () => ({ useTenantId: () => organization }));
const folder = { folder: "/approved", mode: "read_only" } as const;
beforeEach(() => {
  actor = { user: { id: "alice" } };
  organization = "org";
  useProjectFoldersStore.setState({ byProject: {} });
});
it("uses the original account when an asynchronous picker finishes after a switch", () => {
  const { result, rerender } = renderHook(() => useProjectFolder("project"));
  const original = result.current.bind;
  actor = { user: { id: "bob" } };
  rerender();
  act(() => original("project", folder));
  expect(result.current.target).toBeNull();
  actor = { user: { id: "alice" } };
  rerender();
  expect(result.current.target).toEqual(folder);
  act(() => result.current.bind("project", null));
  expect(result.current.target).toBeNull();
});
it("does not bind outside an authenticated organization or expose a draft as a project", () => {
  actor = { user: null };
  organization = null;
  const { result } = renderHook(() => useProjectFolder(null));
  expect(result.current.available).toBe(false);
  expect(result.current.target).toBeNull();
  act(() => result.current.bind("project", folder));
  expect(useProjectFoldersStore.getState().byProject).toEqual({});
  expect(projectFolderKey("alice", null, "project")).toBeNull();
});
