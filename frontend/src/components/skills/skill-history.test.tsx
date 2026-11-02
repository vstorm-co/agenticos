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
import { SkillHistory } from "./skill-history";

vi.mock("@/lib/api-client", async (original) => ({
  ...(await original<typeof import("@/lib/api-client")>()),
  apiClient: { get: vi.fn(), post: vi.fn(), patch: vi.fn(), put: vi.fn(), delete: vi.fn() },
}));
vi.mock("sonner", () => ({ toast: { success: vi.fn(), info: vi.fn(), error: vi.fn() } }));

const RETURNS = { id: "f1", name: "Returns" } as SkillFork;

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

    await userEvent.click(await screen.findByRole("button", { name: "Restore v1" }));
    expect(screen.getByText(/newest version of fork “Returns”/)).toBeInTheDocument();
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
});
