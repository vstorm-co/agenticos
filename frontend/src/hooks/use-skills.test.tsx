import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { useSkill, useSkillResource, useSkills } from "./use-skills";
import { apiClient } from "@/lib/api-client";

vi.mock("@/lib/api-client", () => ({
  apiClient: {
    get: vi.fn(),
    post: vi.fn(),
    patch: vi.fn(),
    delete: vi.fn(),
    uploadMany: vi.fn(),
  },
}));
const toastSuccess = vi.fn();
const toastError = vi.fn();
vi.mock("sonner", () => ({
  toast: {
    success: (...args: unknown[]) => toastSuccess(...args),
    error: (...args: unknown[]) => toastError(...args),
  },
}));

function wrapper({ children }: { children: ReactNode }) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

describe("useSkills", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(apiClient.get).mockResolvedValue({ items: [], total: 0 });
  });

  it("lists skills", async () => {
    vi.mocked(apiClient.get).mockResolvedValue({
      items: [{ id: "s1", name: "refunds", description: "How refunds work", enabled: true }],
      total: 1,
    });
    const { result } = renderHook(() => useSkills(), { wrapper });
    await waitFor(() => expect(result.current.isLoading).toBe(false));
    expect(result.current.skills[0]?.name).toBe("refunds");
  });

  it("asks the database for the slice, rather than filtering what it happens to hold", async () => {
    // An organization's skills grow without bound, so the client never has them
    // all - a client-side filter would search whichever fifty arrived first.
    const { result } = renderHook(() => useSkills({ search: "refund", skip: 50, limit: 50 }), {
      wrapper,
    });
    await waitFor(() => expect(result.current.isLoading).toBe(false));

    expect(apiClient.get).toHaveBeenCalledWith("/skills?q=refund&sort=name&skip=50&limit=50");
  });

  it("sends every picked category to the server, repeated, same as the search", async () => {
    // The filter is a multi-select and `category` repeats in the query string:
    // the server reads two occurrences as "either shelf". Joined or last-wins
    // encodings would silently narrow the filter.
    const { result } = renderHook(
      () => useSkills({ categories: ["devops", "data"], sort: "updated" }),
      { wrapper },
    );
    await waitFor(() => expect(result.current.isLoading).toBe(false));

    expect(apiClient.get).toHaveBeenCalledWith(
      "/skills?category=devops&category=data&sort=updated&skip=0&limit=50",
    );
  });

  it("hands back the organization's category choices alongside the page", async () => {
    vi.mocked(apiClient.get).mockResolvedValue({
      items: [],
      total: 0,
      categories: ["devops", "marketing"],
    });
    const { result } = renderHook(() => useSkills(), { wrapper });
    await waitFor(() => expect(result.current.isLoading).toBe(false));

    expect(result.current.categories).toEqual(["devops", "marketing"]);
  });

  it("reports the count before paging, which is what tells a caller it has a page", async () => {
    vi.mocked(apiClient.get).mockResolvedValue({ items: [], total: 120 });
    const { result } = renderHook(() => useSkills(), { wrapper });
    await waitFor(() => expect(result.current.isLoading).toBe(false));

    expect(result.current.total).toBe(120);
  });

  it("creates a skill", async () => {
    vi.mocked(apiClient.post).mockResolvedValue({ name: "refunds" });
    const { result } = renderHook(() => useSkills(), { wrapper });
    await waitFor(() => expect(result.current.isLoading).toBe(false));

    await result.current.create.mutateAsync({
      name: "refunds",
      description: "How refunds work",
      content: "# Refunds",
    });
    expect(apiClient.post).toHaveBeenCalledWith(
      "/skills",
      expect.objectContaining({ name: "refunds" }),
    );
  });

  it("says an edit reaches every agent at once", async () => {
    // Skills are bound by reference. That is the whole point, and the person
    // editing one should know it before they hit save.
    vi.mocked(apiClient.patch).mockResolvedValue({ name: "refunds" });
    const { result } = renderHook(() => useSkills(), { wrapper });
    await waitFor(() => expect(result.current.isLoading).toBe(false));

    await result.current.update.mutateAsync({ id: "s1", content: "# Refunds v2" });

    expect(apiClient.patch).toHaveBeenCalledWith("/skills/s1", { content: "# Refunds v2" });
    expect(toastSuccess.mock.calls.at(-1)?.[0]).toMatch(/every agent/i);
  });

  it("deletes a skill", async () => {
    vi.mocked(apiClient.delete).mockResolvedValue(undefined);
    const { result } = renderHook(() => useSkills(), { wrapper });
    await waitFor(() => expect(result.current.isLoading).toBe(false));

    await result.current.remove.mutateAsync("s1");
    expect(apiClient.delete).toHaveBeenCalledWith("/skills/s1");
  });
});

const BODY = {
  id: "s1",
  name: "refunds",
  description: "How refunds work",
  content: "# Refunds",
  enabled: true,
  version: 1,
  visibility: "organization",
  owner_user_id: null,
};

describe("useSkill", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(apiClient.get).mockResolvedValue(BODY);
  });

  it("loads the body the list left out", async () => {
    const { result } = renderHook(() => useSkill("s1"), { wrapper });
    await waitFor(() => expect(result.current.skill).toEqual(BODY));
    expect(apiClient.get).toHaveBeenCalledWith("/skills/s1");
  });

  it("asks for nothing until a skill is opened", () => {
    // Bodies can be long; the list page must not fetch one per row.
    renderHook(() => useSkill(null), { wrapper });
    expect(apiClient.get).not.toHaveBeenCalled();
  });

  it("sends the whole editable set, so an unticked toggle is not lost", async () => {
    vi.mocked(apiClient.patch).mockResolvedValue(BODY);
    const { result } = renderHook(() => useSkill("s1"), { wrapper });
    await waitFor(() => expect(result.current.skill).toEqual(BODY));

    await result.current.save.mutateAsync({
      description: "How refunds work",
      content: "# Refunds v2",
      enabled: false,
      category: null,
    });

    expect(apiClient.patch).toHaveBeenCalledWith("/skills/s1", {
      description: "How refunds work",
      content: "# Refunds v2",
      enabled: false,
      category: null,
    });
    expect(toastSuccess.mock.calls.at(-1)?.[0]).toMatch(/every agent/i);
  });
});

/**
 * The rest of the mutation callbacks, and the one deliberate asymmetry.
 *
 * `useSkills.create` has no `onError`, unlike every neighbour: the ways it fails
 * - the name is taken, the description is too long - are things the reader can fix
 * in the dialog still on screen, so the dialog decides where to say it. A toast
 * would put the message somewhere it cannot be acted on and then remove it.
 */
describe("useSkills failures", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(apiClient.get).mockResolvedValue({ items: [], total: 0 });
  });

  it("leaves a failed creation to the dialog", async () => {
    vi.mocked(apiClient.post).mockRejectedValue(new Error("name taken"));
    const { result } = renderHook(() => useSkills(), { wrapper });

    await expect(
      result.current.create.mutateAsync({ name: "refunds", description: "", content: "" }),
    ).rejects.toThrow();

    expect(toastError).not.toHaveBeenCalled();
  });

  it("reports a failed edit", async () => {
    vi.mocked(apiClient.patch).mockRejectedValue(new Error("conflict"));
    const { result } = renderHook(() => useSkills(), { wrapper });

    await expect(result.current.update.mutateAsync({ id: "s1" })).rejects.toThrow();

    expect(toastError).toHaveBeenCalledWith("conflict");
  });

  it("reports a failed delete", async () => {
    vi.mocked(apiClient.delete).mockRejectedValue(new Error("in use by an agent"));
    const { result } = renderHook(() => useSkills(), { wrapper });

    await expect(result.current.remove.mutateAsync("s1")).rejects.toThrow();

    expect(toastError).toHaveBeenCalledWith("in use by an agent");
  });
});

describe("useSkill files", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(apiClient.get).mockResolvedValue(BODY);
  });

  it("adds a file", async () => {
    vi.mocked(apiClient.post).mockResolvedValue({ id: "r1" });
    const { result } = renderHook(() => useSkill("s1"), { wrapper });
    await waitFor(() => expect(result.current.skill).toEqual(BODY));

    await result.current.addResource.mutateAsync({
      name: "references/a.md",
      description: null,
      content: "body",
    });

    expect(apiClient.post).toHaveBeenCalledWith("/skills/s1/resources", {
      name: "references/a.md",
      description: null,
      content: "body",
    });
    expect(toastSuccess).toHaveBeenCalledWith("File added");
  });

  it("reports a rejected file", async () => {
    // Path traversal and non-UTF-8 bodies are both refused server-side.
    vi.mocked(apiClient.post).mockRejectedValue(new Error("bad path"));
    const { result } = renderHook(() => useSkill("s1"), { wrapper });
    await waitFor(() => expect(result.current.skill).toEqual(BODY));

    await expect(
      result.current.addResource.mutateAsync({ name: "../x", description: null, content: "" }),
    ).rejects.toThrow();

    expect(toastError).toHaveBeenCalledWith("bad path");
  });

  it("saves one file", async () => {
    vi.mocked(apiClient.patch).mockResolvedValue({ id: "r1" });
    const { result } = renderHook(() => useSkill("s1"), { wrapper });
    await waitFor(() => expect(result.current.skill).toEqual(BODY));

    await result.current.saveResource.mutateAsync({ id: "r1", content: "new" });

    expect(apiClient.patch).toHaveBeenCalledWith("/skills/s1/resources/r1", { content: "new" });
    expect(toastSuccess).toHaveBeenCalledWith("File saved");
  });

  it("reports a failed file save", async () => {
    vi.mocked(apiClient.patch).mockRejectedValue(new Error("too large"));
    const { result } = renderHook(() => useSkill("s1"), { wrapper });
    await waitFor(() => expect(result.current.skill).toEqual(BODY));

    await expect(result.current.saveResource.mutateAsync({ id: "r1" })).rejects.toThrow();

    expect(toastError).toHaveBeenCalledWith("too large");
  });

  it("removes a file", async () => {
    vi.mocked(apiClient.delete).mockResolvedValue(undefined);
    const { result } = renderHook(() => useSkill("s1"), { wrapper });
    await waitFor(() => expect(result.current.skill).toEqual(BODY));

    await result.current.removeResource.mutateAsync("r1");

    expect(apiClient.delete).toHaveBeenCalledWith("/skills/s1/resources/r1");
    expect(toastSuccess).toHaveBeenCalledWith("File removed");
  });

  it("reports a failed file removal", async () => {
    vi.mocked(apiClient.delete).mockRejectedValue(new Error("gone"));
    const { result } = renderHook(() => useSkill("s1"), { wrapper });
    await waitFor(() => expect(result.current.skill).toEqual(BODY));

    await expect(result.current.removeResource.mutateAsync("r1")).rejects.toThrow();

    expect(toastError).toHaveBeenCalledWith("gone");
  });

  it("uploads a folder under the paths the browser reported", async () => {
    // `webkitRelativePath` is what makes a dropped folder arrive as a folder,
    // with nothing to reconstruct server-side.
    vi.mocked(apiClient.uploadMany).mockResolvedValue({ items: [{}, {}] });
    const { result } = renderHook(() => useSkill("s1"), { wrapper });
    await waitFor(() => expect(result.current.skill).toEqual(BODY));

    const plain = new File(["x"], "a.md");
    const nested = new File(["y"], "b.md");
    Object.defineProperty(nested, "webkitRelativePath", { value: "refs/b.md" });

    await result.current.uploadResources.mutateAsync([plain, nested]);

    const [, , naming] = vi.mocked(apiClient.uploadMany).mock.calls.at(-1)!;
    expect(naming(plain)).toBe("a.md");
    expect(naming(nested)).toBe("refs/b.md");
  });

  it("counts what was uploaded, in the plural only when it should be", async () => {
    vi.mocked(apiClient.uploadMany).mockResolvedValue({ items: [{}] });
    const { result } = renderHook(() => useSkill("s1"), { wrapper });
    await waitFor(() => expect(result.current.skill).toEqual(BODY));

    await result.current.uploadResources.mutateAsync([new File(["x"], "a.md")]);

    expect(toastSuccess).toHaveBeenCalledWith("1 file uploaded");

    vi.mocked(apiClient.uploadMany).mockResolvedValue({ items: [{}, {}, {}] });
    await result.current.uploadResources.mutateAsync([new File(["x"], "a.md")]);

    expect(toastSuccess).toHaveBeenCalledWith("3 files uploaded");
  });

  it("reports a failed upload", async () => {
    vi.mocked(apiClient.uploadMany).mockRejectedValue(new Error("disk full"));
    const { result } = renderHook(() => useSkill("s1"), { wrapper });
    await waitFor(() => expect(result.current.skill).toEqual(BODY));

    await expect(
      result.current.uploadResources.mutateAsync([new File(["x"], "a.md")]),
    ).rejects.toThrow();

    expect(toastError).toHaveBeenCalledWith("disk full");
  });

  it("reports a failed body save", async () => {
    vi.mocked(apiClient.patch).mockRejectedValue(new Error("stale"));
    const { result } = renderHook(() => useSkill("s1"), { wrapper });
    await waitFor(() => expect(result.current.skill).toEqual(BODY));

    // The whole editable set, because that is what `SkillEdit` is - a partial
    // would silently reset whatever it omitted.
    await expect(
      result.current.save.mutateAsync({
        description: "d",
        content: "x",
        enabled: true,
        category: null,
      }),
    ).rejects.toThrow();

    expect(toastError).toHaveBeenCalledWith("stale");
  });
});

describe("useSkillResource", () => {
  beforeEach(() => vi.clearAllMocks());

  it("fetches one file's body", async () => {
    vi.mocked(apiClient.get).mockResolvedValue({ id: "r1", content: "hello" });
    const { result } = renderHook(() => useSkillResource("s1", "r1"), { wrapper });

    await waitFor(() => expect(result.current.resource).toBeDefined());

    expect(apiClient.get).toHaveBeenCalledWith("/skills/s1/resources/r1");
  });

  it("asks for nothing until a file is opened", () => {
    renderHook(() => useSkillResource("s1", null), { wrapper });

    expect(apiClient.get).not.toHaveBeenCalled();
  });

  it("asks for nothing when no skill is open either", () => {
    renderHook(() => useSkillResource(null, "r1"), { wrapper });

    expect(apiClient.get).not.toHaveBeenCalled();
  });
});
