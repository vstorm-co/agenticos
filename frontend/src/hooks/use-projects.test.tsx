import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { toast } from "sonner";
import { beforeEach, describe, expect, it, vi } from "vitest";

import {
  uploadPath,
  useProject,
  useProjectChats,
  useProjectFiles,
  useProjects,
} from "./use-projects";
import * as api from "@/lib/projects-api";
import type { Project } from "@/types/projects";

vi.mock("@/lib/projects-api", () => ({
  listProjects: vi.fn(),
  getProject: vi.fn(),
  createProject: vi.fn(),
  updateProject: vi.fn(),
  deleteProject: vi.fn(),
  listProjectFiles: vi.fn(),
  listProjectChats: vi.fn(),
  uploadProjectFile: vi.fn(),
  createProjectFolder: vi.fn(),
  removeProjectPath: vi.fn(),
  moveProjectPath: vi.fn(),
  moveProjectWorkspace: vi.fn(),
}));
vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));

function wrapper({ children }: { children: ReactNode }) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

const PROJECT = { id: "p-1", name: "Launch" } as Project;
const LISTING = { scope: "project", items: [], total: 0 };

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(api.listProjects).mockResolvedValue({ items: [PROJECT], total: 1 });
  vi.mocked(api.getProject).mockResolvedValue(PROJECT);
  vi.mocked(api.createProject).mockResolvedValue(PROJECT);
  vi.mocked(api.updateProject).mockResolvedValue(PROJECT);
  vi.mocked(api.deleteProject).mockResolvedValue(undefined);
  vi.mocked(api.listProjectFiles).mockResolvedValue(LISTING as never);
  vi.mocked(api.uploadProjectFile).mockResolvedValue(undefined);
  vi.mocked(api.createProjectFolder).mockResolvedValue({ path: "docs" });
  vi.mocked(api.removeProjectPath).mockResolvedValue(undefined);
});

describe("useProjects", () => {
  it("lists one page and says so when one is created", async () => {
    const { result } = renderHook(() => useProjects({ search: "la" }), { wrapper });
    await waitFor(() => expect(result.current.projects).toEqual([PROJECT]));
    expect(result.current.total).toBe(1);
    expect(api.listProjects).toHaveBeenCalledWith({ search: "la", skip: 0, limit: 50 });

    await act(() => result.current.create.mutateAsync({ name: "Launch" }));
    expect(toast.success).toHaveBeenCalledWith("Project Launch created");
  });

  it("asks for nothing when it is not wanted", () => {
    const { result } = renderHook(() => useProjects({ enabled: false }), { wrapper });
    expect(result.current.projects).toEqual([]);
    expect(api.listProjects).not.toHaveBeenCalled();
  });
});

describe("useProject", () => {
  it("reads one, saves it and deletes it, toasting each", async () => {
    const { result } = renderHook(() => useProject("p-1"), { wrapper });
    await waitFor(() => expect(result.current.project).toEqual(PROJECT));

    await act(() => result.current.update.mutateAsync({ instructions: "Be brief." }));
    expect(api.updateProject).toHaveBeenCalledWith("p-1", { instructions: "Be brief." });
    await act(() => result.current.remove.mutateAsync());
    expect(toast.success).toHaveBeenLastCalledWith(
      "Project deleted. Its chats are ordinary chats now.",
    );
  });

  it("says why a save or a delete was refused", async () => {
    vi.mocked(api.updateProject).mockRejectedValue(new Error("no"));
    vi.mocked(api.deleteProject).mockRejectedValue(new Error("no"));
    const { result } = renderHook(() => useProject("p-1"), { wrapper });
    await waitFor(() => expect(result.current.project).not.toBeNull());

    await act(async () => {
      await result.current.update.mutateAsync({}).catch(() => undefined);
      await result.current.remove.mutateAsync().catch(() => undefined);
    });
    expect(toast.error).toHaveBeenCalledTimes(2);
  });
});

describe("useProjectFiles", () => {
  it("uploads each file into its folder, makes folders and removes paths", async () => {
    const { result } = renderHook(() => useProjectFiles("p-1"), { wrapper });
    await waitFor(() => expect(result.current.files).toEqual(LISTING));

    const a = new File(["a"], "a.md");
    const b = new File(["b"], "b.md");
    // Each upload reports its progress into the bar for its file, and the bar goes
    // once the file is in.
    vi.mocked(api.uploadProjectFile).mockImplementation(async (_id, _file, _path, progress) => {
      progress.onPercent(40);
      progress.onPercent(null);
    });
    await act(() => result.current.upload.mutateAsync({ files: [a, b], folder: "docs" }));
    expect(api.uploadProjectFile).toHaveBeenCalledWith(
      "p-1",
      b,
      "docs/b.md",
      expect.objectContaining({ failed: "The upload failed" }),
    );
    expect(toast.success).toHaveBeenCalledWith("2 files added");
    expect(result.current.uploads).toEqual([]);

    await act(() => result.current.addFolder.mutateAsync("notes"));
    expect(api.createProjectFolder).toHaveBeenCalledWith("p-1", "notes");
    await act(() => result.current.move.mutateAsync({ source: "notes", destination: "drafts" }));
    expect(api.moveProjectPath).toHaveBeenCalledWith("p-1", "notes", "drafts");
    await act(() => result.current.remove.mutateAsync("notes"));
    expect(toast.success).toHaveBeenLastCalledWith("Removed");
  });

  it("names a refused write and an unreadable listing", async () => {
    vi.mocked(api.listProjectFiles).mockRejectedValue(new Error("down"));
    vi.mocked(api.uploadProjectFile).mockRejectedValue(new Error("too big"));
    vi.mocked(api.createProjectFolder).mockRejectedValue(new Error("no"));
    vi.mocked(api.removeProjectPath).mockRejectedValue(new Error("no"));
    vi.mocked(api.moveProjectPath).mockRejectedValue(new Error("no"));
    const { result } = renderHook(() => useProjectFiles("p-1"), { wrapper });
    await waitFor(() => expect(result.current.error).not.toBeNull());

    await act(async () => {
      await result.current.upload
        .mutateAsync({ files: [new File(["a"], "a")], folder: "" })
        .catch(() => undefined);
      await result.current.addFolder.mutateAsync("x").catch(() => undefined);
      await result.current.remove.mutateAsync("x").catch(() => undefined);
      await result.current.move
        .mutateAsync({ source: "x", destination: "y" })
        .catch(() => undefined);
    });
    expect(toast.error).toHaveBeenCalledTimes(4);
  });
});

describe("useProjectChats", () => {
  it("lists everybody's chats in the project, a page at a time", async () => {
    vi.mocked(api.listProjectChats)
      .mockResolvedValueOnce({ items: [{ id: "c-1" }, { id: "c-2" }] as never, total: 3 })
      .mockResolvedValueOnce({ items: [{ id: "c-3" }] as never, total: 3 });
    const { result } = renderHook(() => useProjectChats("p-1"), { wrapper });
    await waitFor(() => expect(result.current.total).toBe(3));
    expect(api.listProjectChats).toHaveBeenCalledWith("p-1", 0, 50);
    expect(result.current.hasMore).toBe(true);

    act(() => result.current.loadMore());
    await waitFor(() => expect(result.current.chats).toHaveLength(3));
    expect(api.listProjectChats).toHaveBeenLastCalledWith("p-1", 2, 50);
    expect(result.current.hasMore).toBe(false);
  });

  it("starts empty", () => {
    vi.mocked(api.listProjectChats).mockReturnValue(new Promise(() => undefined));
    const { result } = renderHook(() => useProjectChats("p-1"), { wrapper });
    expect(result.current.chats).toEqual([]);
    expect(result.current.total).toBe(0);
  });
});

describe("uploadPath", () => {
  it("keeps a folder upload's tree and puts a file at the top otherwise", () => {
    const nested = new File(["x"], "a.md");
    Object.defineProperty(nested, "webkitRelativePath", { value: "brand/a.md" });
    expect(uploadPath(nested, "")).toBe("brand/a.md");
    expect(uploadPath(new File(["x"], "b.md"), "")).toBe("b.md");
  });
});

it("queues a sandbox transfer and reports a refused transfer without dropping the project", async () => {
  const { result } = renderHook(() => useProject("p-1"), { wrapper });
  await waitFor(() => expect(result.current.project).toEqual(PROJECT));
  vi.mocked(api.moveProjectWorkspace).mockResolvedValue({
    job_id: "j",
    status: "queued",
    target_name: "Cloud",
    copied_files: 0,
    total_files: 0,
    copied_bytes: 0,
  });
  await act(() => result.current.moveWorkspace.mutateAsync("cloud"));
  expect(api.moveProjectWorkspace).toHaveBeenCalledWith("p-1", "cloud");
  vi.mocked(api.moveProjectWorkspace).mockRejectedValue(new Error("active run"));
  await act(async () => {
    await result.current.moveWorkspace.mutateAsync("cloud").catch(() => undefined);
  });
  expect(toast.error).toHaveBeenCalled();
  expect(result.current.project?.id).toBe("p-1");
});
