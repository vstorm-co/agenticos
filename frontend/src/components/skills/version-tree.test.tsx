import type { ReactElement } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render as renderBare, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { apiClient } from "@/lib/api-client";
import type { SkillAgentUsage } from "@/types/skill-versions";
import { VersionTree } from "./version-tree";

vi.mock("@/lib/api-client", async (original) => ({
  ...(await original<typeof import("@/lib/api-client")>()),
  apiClient: { get: vi.fn(), post: vi.fn(), patch: vi.fn(), put: vi.fn(), delete: vi.fn() },
}));

function render(ui: ReactElement) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return renderBare(<QueryClientProvider client={client}>{ui}</QueryClientProvider>);
}

beforeEach(() => vi.clearAllMocks());

function onMain(name: string): SkillAgentUsage {
  return {
    agent: { id: name, name, slug: name.toLowerCase() },
    via_specialist: null,
    draft_only: false,
    binding: {
      state: "main",
      version: { id: "m25", number: 25, fork_id: null },
      fork: null,
      behind_main: 0,
    },
    agent_version: 1,
    environments: [],
    draft_differs: false,
    can_change: false,
    can_publish: false,
  };
}

describe("VersionTree", () => {
  it("folds the versions nobody uses and unfolds them on request", async () => {
    render(<VersionTree skillId="s1" mainLatest={25} forks={[]} agents={[]} error={null} />);

    expect(screen.getByText("v25")).toBeInTheDocument();
    expect(screen.queryByText("v12")).toBeNull();
    await userEvent.click(screen.getByRole("button", { name: "23 versions (v24–v2)" }));

    expect(screen.getByText("v12")).toBeInTheDocument();
  });

  it("names every agent in the box of the version it reads", () => {
    render(
      <VersionTree
        skillId="s1"
        mainLatest={25}
        forks={[]}
        agents={["Ana", "Bo", "Cy", "Di", "Ed"].map(onMain)}
        error={null}
      />,
    );

    const newest = screen.getByText("v25").closest("li")!;
    for (const name of ["Ana", "Bo", "Cy", "Di", "Ed"]) {
      expect(within(newest).getByText(name)).toBeInTheDocument();
    }
  });

  it("puts the versions picked side by side, and takes them out again", async () => {
    vi.mocked(apiClient.get).mockImplementation(async (url: string) => {
      if (url.includes("/versions?")) {
        return {
          items: [
            { id: "m25", number: 25 },
            { id: "m1", number: 1 },
          ],
          total: 25,
        };
      }
      if (url.endsWith("/m1")) {
        return { id: "m1", number: 1, description: "First", content: "Start.", resources: [] };
      }
      return {
        id: "m25",
        number: 25,
        description: "Refunds, by the book",
        content: "Answer from the policy.",
        resources: [
          { name: "policy.md", description: "The policy", size_bytes: 1, digest: "d" },
          { name: "notes.md", description: null, size_bytes: 1, digest: "e" },
        ],
      };
    });
    render(<VersionTree skillId="s1" mainLatest={25} forks={[]} agents={[]} error={null} />);

    const compare = screen.getByRole("button", { name: "Compare v25" });
    await userEvent.click(compare);
    expect(compare).toHaveAttribute("aria-pressed", "true");
    const column = await screen.findByRole("region", { name: "v25" });
    expect(await within(column).findByText("Answer from the policy.")).toBeVisible();
    expect(within(column).getByText("Refunds, by the book")).toBeVisible();
    expect(within(column).getByText("policy.md")).toBeVisible();
    expect(screen.getByText(/Pick another version/)).toBeVisible();

    await userEvent.click(screen.getByRole("button", { name: "Compare v1" }));
    expect(screen.getByText("2 versions")).toBeVisible();
    expect(
      await within(screen.getByRole("region", { name: "v1" })).findByText("No files."),
    ).toBeVisible();
    await userEvent.click(screen.getByRole("button", { name: "Remove v1 from the comparison" }));
    expect(screen.getByText("1 version")).toBeVisible();
    await userEvent.click(screen.getByRole("button", { name: "Compare v25" }));
    expect(screen.queryByText("Comparison")).toBeNull();
  });

  it("says when a compared version cannot be read, and clears the comparison", async () => {
    vi.mocked(apiClient.get).mockRejectedValue(new Error("Versions are down"));
    render(<VersionTree skillId="s1" mainLatest={3} forks={[]} agents={[]} error={null} />);

    await userEvent.click(screen.getByRole("button", { name: "Compare v2" }));
    expect(await screen.findByText("Versions are down")).toBeVisible();
    await userEvent.click(screen.getByRole("button", { name: "Clear" }));
    expect(screen.queryByText("Comparison")).toBeNull();
  });
});

describe("VersionTree's forks", () => {
  const fork = (latest: number | null) => ({
    id: "f1",
    skill_id: "s1",
    name: "Returns",
    base: { id: "m3", number: 3 },
    latest: latest === null ? null : { id: `r${latest}`, number: latest },
    changes: latest ?? 0,
    behind_main: 22,
    agents: 1,
    archive_candidate: false,
    archived_at: null,
    created_at: "2026-11-01T10:00:00Z",
  });
  const onFork = (latest: number | null): SkillAgentUsage => ({
    ...onMain("Refunds"),
    binding: {
      state: "fork",
      version: { id: "r", number: latest ?? 3, fork_id: "f1" },
      fork: { id: "f1", name: "Returns", base_number: 3, changes: latest ?? 0 },
      behind_main: 22,
    },
  });

  it("draws a fork off its base with its own versions and agents", async () => {
    render(
      <VersionTree
        skillId="s1"
        mainLatest={25}
        forks={[fork(2)]}
        agents={[onFork(2)]}
        error={null}
      />,
    );

    expect(screen.getByText("Fork “Returns”")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Compare Returns v2" }));
    expect(screen.getByRole("region", { name: "Returns v2" })).toBeInTheDocument();
    expect(apiClient.get).toHaveBeenCalledWith(expect.stringContaining("fork_id=f1"));
    expect(screen.getByText("2 changes · 22 behind main")).toBeInTheDocument();
    // Main's v2 and the fork's own v2, told apart by the fork's name.
    expect(screen.getByText("v2")).toBeInTheDocument();
    expect(screen.getAllByText("Returns v2")[0]).toBeInTheDocument();
    expect(screen.getByText("Refunds")).toBeInTheDocument();
  });

  it("holds the agents of a fork with no versions of its own on the branch", () => {
    render(
      <VersionTree
        skillId="s1"
        mainLatest={25}
        forks={[fork(null)]}
        agents={[onFork(null)]}
        error={null}
      />,
    );

    expect(screen.getByText("no changes yet · 22 behind main")).toBeInTheDocument();
    const branch = screen.getByText("No version of its own yet").closest("li")!;
    expect(within(branch).getByText("Refunds")).toBeInTheDocument();
    expect(within(branch).queryByRole("button", { name: /^Compare/ })).toBeNull();
  });

  it("says when the agents cannot be read instead of drawing an empty tree", () => {
    render(
      <VersionTree
        skillId="s1"
        mainLatest={25}
        forks={[]}
        agents={[]}
        error={new Error("offline")}
      />,
    );

    expect(screen.getByText("offline")).toBeInTheDocument();
    expect(screen.queryByText("v25")).toBeNull();
  });
});
