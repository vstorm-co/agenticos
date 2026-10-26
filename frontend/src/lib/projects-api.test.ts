import { beforeEach, describe, expect, it, vi } from "vitest";

import * as api from "./projects-api";
import { apiClient } from "./api-client";
import { postWithProgress } from "./upload-with-progress";

vi.mock("./api-client", () => ({
  apiClient: { get: vi.fn(), post: vi.fn(), patch: vi.fn(), delete: vi.fn(), raw: vi.fn() },
}));
vi.mock("./upload-with-progress", () => ({ postWithProgress: vi.fn() }));

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(apiClient.get).mockResolvedValue({ items: [], total: 0 });
  vi.mocked(apiClient.post).mockResolvedValue({ path: "a.md" });
  vi.mocked(apiClient.patch).mockResolvedValue({ id: "p-1" });
  vi.mocked(apiClient.delete).mockResolvedValue(undefined);
  vi.mocked(apiClient.raw).mockImplementation(async () => new Response("# Brief"));
});

describe("the projects client", () => {
  it("pages and searches the list, leaving an empty search off the address", async () => {
    await api.listProjects({ search: "", skip: 0, limit: 10 });
    expect(apiClient.get).toHaveBeenLastCalledWith("/projects?skip=0&limit=10");
    await api.listProjects({ search: "launch", skip: 10, limit: 10 });
    expect(apiClient.get).toHaveBeenLastCalledWith("/projects?skip=10&limit=10&q=launch");
  });

  it("reads, creates, changes and deletes one", async () => {
    await api.getProject("p-1");
    expect(apiClient.get).toHaveBeenLastCalledWith("/projects/p-1");
    await api.createProject({ name: "Launch" });
    expect(apiClient.post).toHaveBeenLastCalledWith("/projects", { name: "Launch" });
    await api.updateProject("p-1", { instructions: "Be brief." });
    expect(apiClient.patch).toHaveBeenCalledWith("/projects/p-1", { instructions: "Be brief." });
    await api.deleteProject("p-1");
    expect(apiClient.delete).toHaveBeenLastCalledWith("/projects/p-1");
  });

  it("reads which project a conversation is in, and none for one outside", async () => {
    vi.mocked(apiClient.get).mockResolvedValueOnce({ id: "c-1", project_id: "p-1" });
    expect(await api.projectOfConversation("c-1")).toBe("p-1");
    expect(apiClient.get).toHaveBeenLastCalledWith("/conversations/c-1/metadata");
    vi.mocked(apiClient.get).mockResolvedValueOnce({ id: "c-2" });
    expect(await api.projectOfConversation("c-2")).toBeNull();
  });

  it("reads a file's bytes, for a download too, and its text from them", async () => {
    await api.readProjectBytes("p-1", "docs/a b.md");
    expect(apiClient.raw).toHaveBeenLastCalledWith("/projects/p-1/files/raw?path=docs%2Fa%20b.md");
    await api.readProjectBytes("p-1", "a.md", { download: true });
    expect(apiClient.raw).toHaveBeenLastCalledWith(
      "/projects/p-1/files/raw?path=a.md&download=true",
    );
    await expect(api.readProjectText("p-1", "a.md")).resolves.toEqual({
      content: "# Brief",
      truncated: false,
    });
  });

  it("lists, uploads into a folder, makes folders and removes paths", async () => {
    await api.listProjectFiles("p-1");
    expect(apiClient.get).toHaveBeenLastCalledWith("/projects/p-1/files");

    await api.listProjectChats("p-1", 50, 50);
    expect(apiClient.get).toHaveBeenLastCalledWith("/projects/p-1/chats?skip=50&limit=50");

    const file = new File(["x"], "in.csv");
    const progress = { organizationId: "org-1", onPercent: vi.fn(), failed: "Upload failed" };
    await api.uploadProjectFile("p-1", file, "data/in.csv", progress);
    const [endpoint, form, options] = vi.mocked(postWithProgress).mock.calls.at(-1)!;
    expect(endpoint).toBe("/projects/p-1/files");
    expect(form.get("path")).toBe("data/in.csv");
    expect((form.get("file") as File).name).toBe("in.csv");
    expect(options).toBe(progress);

    await api.createProjectFolder("p-1", "docs");
    expect(apiClient.post).toHaveBeenLastCalledWith("/projects/p-1/folders", { path: "docs" });
    await api.removeProjectPath("p-1", "docs/old.md");
    expect(apiClient.delete).toHaveBeenLastCalledWith("/projects/p-1/files?path=docs%2Fold.md");
  });
});
