import type { ReactNode } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { toast } from "sonner";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { PAGE_SIZE } from "@/components/ui";
import { apiClient } from "@/lib/api-client";
import { ApiError } from "@/lib/api-error";
import type { SkillFork, SkillVersionSummary } from "@/types/skill-versions";
import { skillSession } from "@/test-utils/skill-improvement";
import { SkillHistory } from "./skill-history";

vi.mock("@/lib/api-client", async (original) => ({
  ...(await original<typeof import("@/lib/api-client")>()),
  apiClient: { get: vi.fn(), post: vi.fn(), patch: vi.fn(), put: vi.fn(), delete: vi.fn() },
}));
vi.mock("sonner", () => ({ toast: { success: vi.fn(), info: vi.fn(), error: vi.fn() } }));
const access = vi.hoisted(() => ({ runsView: false }));
vi.mock("@/hooks/use-permissions", () => ({
  usePermissions: () => ({ can: () => access.runsView, isLoading: false }),
}));
const held = vi.hoisted(() => ({ sessions: [] as unknown[] }));

const RETURNS = {
  id: "f1",
  name: "Returns",
  base: { id: "m7", number: 7 },
  started_from: { id: "m7", number: 7 },
} as SkillFork;

function version(number: number, extra: Partial<SkillVersionSummary> = {}): SkillVersionSummary {
  return {
    id: `m${number}`,
    skill_id: "s1",
    fork_id: null,
    number,
    source: "edit",
    previous: number > 1 ? { id: `m${number - 1}`, number: number - 1, fork_id: null } : null,
    restored_from: null,
    proposal_id: null,
    created_by: null,
    created_at: "2026-11-01T10:00:00Z",
    agents: 2,
    ...extra,
  };
}

function serve(total = 2) {
  vi.mocked(apiClient.get).mockImplementation(async (path: string) => {
    if (path === "/skills/s1/improvements") return held.sessions;
    if (path.startsWith("/skills/s1/versions?")) {
      return { items: [version(2), version(1, { source: "backfill" })], total };
    }
    return {
      ...version(Number(path.slice(-1))),
      description: "Returns.",
      content: path.endsWith("m2") ? "Refund within 14 days." : "Refund within 30 days.",
      resources: [],
    };
  });
}

function mount(props: Partial<React.ComponentProps<typeof SkillHistory>> = {}) {
  const onLine = vi.fn();
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <SkillHistory
      skillId="s1"
      forkId={null}
      forkName={null}
      latestId="m2"
      canEdit
      forks={[RETURNS]}
      onLine={onLine}
      {...props}
    />,
    {
      wrapper: ({ children }: { children: ReactNode }) => (
        <QueryClientProvider client={client}>{children}</QueryClientProvider>
      ),
    },
  );
  return { onLine };
}

beforeEach(() => {
  vi.clearAllMocks();
  serve();
});

describe("SkillHistory", () => {
  it("names each version's source, author and the agents on it", async () => {
    mount();

    expect(await screen.findByText("As it was when versions began")).toBeInTheDocument();
    expect(screen.getAllByText(/Unknown · .* · used by 2 agents/)).toHaveLength(2);
  });

  it("names a version a merge made, from main or from a fork", async () => {
    vi.mocked(apiClient.get).mockImplementation(async (path: string) =>
      path.startsWith("/skills/s1/versions?")
        ? {
            items: [version(3, { source: "from_fork" }), version(2, { source: "catch_up" })],
            total: 2,
          }
        : [],
    );
    mount();

    expect(await screen.findByText("Moved in from a fork")).toBeInTheDocument();
    expect(screen.getByText("Caught up with main")).toBeInTheDocument();
  });

  it("shows a version's changes against the one before it, and hides them again", async () => {
    mount();
    const [newest] = await screen.findAllByRole("button", { name: "Show changes" });

    await userEvent.click(newest!);
    expect(await screen.findByText("Instructions")).toBeInTheDocument();
    expect(apiClient.get).toHaveBeenCalledWith("/skills/s1/versions/m1");

    await userEvent.click(screen.getByRole("button", { name: "Hide changes" }));
    expect(screen.queryByText("Instructions")).toBeNull();
  });

  it("switches between main and a fork", async () => {
    const { onLine } = mount();

    await userEvent.click(await screen.findByRole("button", { name: "fork “Returns”" }));
    expect(onLine).toHaveBeenCalledWith("f1");
    await userEvent.click(screen.getByRole("button", { name: "main" }));
    expect(onLine).toHaveBeenCalledWith(null);
  });

  it("pages through a long history", async () => {
    serve(PAGE_SIZE + 5);
    mount();

    await userEvent.click(await screen.findByRole("button", { name: /next/i }));
    expect(apiClient.get).toHaveBeenCalledWith(
      `/skills/s1/versions?skip=${PAGE_SIZE}&limit=${PAGE_SIZE}`,
    );
  });

  it("says a fork's restore reaches the fork's agents", async () => {
    mount({ forkId: "f1", forkName: "Returns" });

    expect(await screen.findByText("Returns v2")).toBeInTheDocument();
    await userEvent.click(await screen.findByRole("button", { name: "Restore Returns v1" }));
    expect(
      screen.getByText(/Returns v1 comes back as the newest version of fork “Returns”/),
    ).toBeInTheDocument();
  });

  it("says why a restore was refused and closes the question", async () => {
    vi.mocked(apiClient.post).mockRejectedValue(
      new ApiError(409, "The line moved", {
        error: { code: "CONCURRENT_CHANGE", message: "The line moved" },
      }),
    );
    mount();

    await userEvent.click(await screen.findByRole("button", { name: "Restore v1" }));
    await userEvent.click(screen.getByRole("button", { name: "Restore" }));

    expect(toast.error).toHaveBeenCalledWith("The line moved");
    expect(screen.queryByText(/comes back as the newest version/)).toBeNull();
  });

  it("drops the question when the person cancels", async () => {
    mount();

    await userEvent.click(await screen.findByRole("button", { name: "Restore v1" }));
    await userEvent.click(screen.getByRole("button", { name: "Cancel" }));

    expect(apiClient.post).not.toHaveBeenCalled();
    expect(screen.queryByText(/comes back as the newest version/)).toBeNull();
  });

  it("offers no Restore on a line with nothing to write over", async () => {
    mount({ latestId: null });

    await screen.findByText("As it was when versions began");
    expect(screen.queryByRole("button", { name: /^Restore/ })).toBeNull();
  });

  it("says when the history cannot be read", async () => {
    vi.mocked(apiClient.get).mockRejectedValue(
      new ApiError(500, "Boom", { error: { code: "INTERNAL", message: "Boom" } }),
    );
    mount({ forks: [] });

    expect(await screen.findByText("Boom")).toBeInTheDocument();
  });

  it("says where a fork starts on main, not where it last caught up", async () => {
    mount({
      forks: [{ ...RETURNS, base: { id: "m2", number: 2 }, started_from: { id: "m1", number: 1 } }],
    });
    const start = await screen.findByText("Fork “Returns” starts here");
    expect(start.closest("li")).toHaveTextContent("v1");
    expect(screen.getAllByText("Fork “Returns” starts here")).toHaveLength(1);
  });

  it("says what a fork with no version of its own reads", async () => {
    vi.mocked(apiClient.get).mockResolvedValue({ items: [], total: 0 });
    mount({ forkId: "f1", forkName: "Returns", latestId: null });
    expect(
      await screen.findByText(/No version of its own yet: the fork reads v7 on main/),
    ).toBeInTheDocument();
  });

  it("lists the line's Improve sessions beside its versions, each tied to the version it applied", async () => {
    access.runsView = true;
    held.sessions = [
      skillSession({
        id: "open-1",
        status: "waiting",
        outcome: null,
        created_by: { id: "u1", name: "Anna" },
        spent_usd: "0.12",
      }),
      skillSession({
        id: "done-1",
        status: "accepted",
        outcome: "applied",
        applied_version_id: "m2",
      }),
      skillSession({
        id: "far-1",
        status: "accepted",
        outcome: "applied",
        applied_version_id: "m9",
      }),
      skillSession({ id: "gone-1", status: "stopped", outcome: null, stop_reason: "expired" }),
      skillSession({ id: "bad-1", status: "failed", outcome: null }),
      skillSession({ id: "fork-1", status: "accepted", outcome: "forked" }),
      skillSession({ id: "none-1", status: "stopped", outcome: null, stop_reason: "no_change" }),
    ];
    serve();
    mount();

    const card = await screen.findByText("Improve sessions");
    expect(card).toBeInTheDocument();
    expect(await screen.findByRole("link", { name: "Continue" })).toHaveAttribute(
      "href",
      "/skills/s1/improve/open-1",
    );
    expect(screen.getByText(/Anna · .* · main · spent \$0\.12/)).toBeInTheDocument();
    expect(screen.getByText("Applied as v2")).toBeInTheDocument();
    expect(screen.getByText("Applied")).toBeInTheDocument();
    for (const text of ["Expired", "Failed", "Made a fork", "Stopped without a change"]) {
      expect(screen.getByText(text)).toBeInTheDocument();
    }
    expect(screen.getByRole("link", { name: "From its Improve session" })).toHaveAttribute(
      "href",
      "/skills/s1/improve/done-1",
    );
    access.runsView = false;
    held.sessions = [];
  });

  it("says when the line has no Improve sessions, and leaves them out without runs:view", async () => {
    access.runsView = true;
    serve();
    mount();
    expect(await screen.findByText("Nobody has improved this line yet.")).toBeInTheDocument();
    access.runsView = false;
  });

  it("reads older Improve sessions a page at a time", async () => {
    access.runsView = true;
    serve();
    const versions = vi.mocked(apiClient.get).getMockImplementation()!;
    const page = (from: number, count: number) =>
      Array.from({ length: count }, (_, index) =>
        skillSession({ id: `s-${from + index}`, status: "accepted", outcome: "discarded" }),
      );
    vi.mocked(apiClient.get).mockImplementation(async (path, options) => {
      if (path === "/skills/s1/improvements") {
        const skip = (options?.params as Record<string, string> | undefined)?.skip;
        return skip === "0" ? page(0, 20) : page(20, 3);
      }
      return versions(path, options);
    });
    mount();

    expect(await screen.findByText("Newest 20")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Show older sessions" }));
    expect(await screen.findByText("23 sessions")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Show older sessions" })).toBeNull();
    expect(apiClient.get).toHaveBeenCalledWith("/skills/s1/improvements", {
      params: { main: "true", skip: "20", limit: "20" },
    });
    access.runsView = false;
  });

  it("says when the line's Improve sessions cannot be read", async () => {
    access.runsView = true;
    serve();
    const versions = vi.mocked(apiClient.get).getMockImplementation()!;
    vi.mocked(apiClient.get).mockImplementation(async (path: string, ...rest: unknown[]) => {
      if (path === "/skills/s1/improvements") throw new Error("Sessions are down");
      return versions(path, ...(rest as []));
    });
    mount();
    expect(await screen.findByText("Sessions are down")).toBeInTheDocument();
    access.runsView = false;
  });
});
