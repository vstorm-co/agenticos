import type { ReactNode } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { apiClient } from "@/lib/api-client";
import type { SkillVersionRead } from "@/types/skill-versions";
import { fileChanges, VersionDiff } from "./version-diff";

vi.mock("@/lib/api-client", async (original) => ({
  ...(await original<typeof import("@/lib/api-client")>()),
  apiClient: { get: vi.fn(), post: vi.fn(), patch: vi.fn(), put: vi.fn(), delete: vi.fn() },
}));

function read(id: string, extra: Partial<SkillVersionRead>): SkillVersionRead {
  return {
    id,
    skill_id: "s1",
    fork_id: null,
    number: 1,
    source: "edit",
    previous: null,
    restored_from: null,
    proposal_id: null,
    created_by: null,
    created_at: "2026-11-01T10:00:00Z",
    agents: 0,
    description: "Returns.",
    content: "Refund within 30 days.",
    resources: [],
    ...extra,
  };
}

function mount(versionId: string, previousId: string | null) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(<VersionDiff skillId="s1" versionId={versionId} previousId={previousId} />, {
    wrapper: ({ children }: { children: ReactNode }) => (
      <QueryClientProvider client={client}>{children}</QueryClientProvider>
    ),
  });
}

beforeEach(() => vi.clearAllMocks());

describe("fileChanges", () => {
  it("names the files added, removed and changed between two versions", () => {
    const file = (name: string, digest: string) => ({
      name,
      description: null,
      size_bytes: 10,
      digest,
    });
    // b.md keeps its size and changes its content: only the digest can tell.
    expect(
      fileChanges(
        [file("a.md", "aa"), file("b.md", "b1"), file("c.md", "cc")],
        [file("a.md", "aa"), file("b.md", "b2"), file("d.md", "dd")],
      ),
    ).toEqual({ added: ["d.md"], removed: ["c.md"], changed: ["b.md"] });
  });

  it("counts a new description on a file as a change to it", () => {
    const file = { name: "a.md", size_bytes: 10, digest: "aa" };
    expect(
      fileChanges([{ ...file, description: null }], [{ ...file, description: "Read first" }]),
    ).toEqual({ added: [], removed: [], changed: ["a.md"] });
  });
});

describe("VersionDiff", () => {
  it("shows what the version changed against the one it came from", async () => {
    vi.mocked(apiClient.get).mockImplementation(async (path: string) =>
      path.endsWith("/m2")
        ? read("m2", {
            content: "Refund within 14 days.",
            resources: [{ name: "form.pdf", description: null, size_bytes: 3, digest: "f1" }],
          })
        : read("m1", {}),
    );
    mount("m2", "m1");

    expect(await screen.findByText("Instructions")).toBeInTheDocument();
    expect(screen.queryByText("Description")).toBeNull();
    expect(screen.getByText("form.pdf")).toBeInTheDocument();
    expect(screen.getByText("added")).toBeInTheDocument();
  });

  it("says when only the files changed", async () => {
    vi.mocked(apiClient.get).mockImplementation(async (path: string) =>
      path.endsWith("/m2")
        ? read("m2", {
            resources: [{ name: "form.pdf", description: null, size_bytes: 3, digest: "f1" }],
          })
        : read("m1", {}),
    );
    mount("m2", "m1");

    expect(await screen.findByText("The instructions did not change.")).toBeInTheDocument();
  });
});

describe("VersionDiff's edges", () => {
  it("compares a first version with nothing", async () => {
    vi.mocked(apiClient.get).mockResolvedValue(read("m1", {}));
    mount("m1", null);

    expect(await screen.findByText("Instructions")).toBeInTheDocument();
    expect(screen.getByText("Description")).toBeInTheDocument();
    expect(apiClient.get).toHaveBeenCalledTimes(1);
  });

  it("waits for both versions before drawing", () => {
    vi.mocked(apiClient.get).mockReturnValue(new Promise(() => undefined));
    mount("m2", "m1");

    expect(screen.getByLabelText("Loading the changes")).toBeInTheDocument();
  });

  it("says when a version cannot be read", async () => {
    vi.mocked(apiClient.get).mockRejectedValue(new Error("gone"));
    mount("m2", "m1");

    expect(await screen.findByText("gone")).toBeInTheDocument();
  });
});
