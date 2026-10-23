import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { evalRun } from "@/test-utils/eval-runs";
import { Perm } from "@/types/permissions";
import EvalRunsPage from "./page";

/**
 * `/evals`, where the dashboard's Eval runs card sees all: every run the reader
 * may see, a page at a time, behind `runs:view` like the API it reads.
 */

const { get, granted, push } = vi.hoisted(() => ({
  get: vi.fn(),
  granted: { perms: [] as string[] },
  push: vi.fn(),
}));
vi.mock("@/lib/api-client", () => ({
  apiClient: { get, post: vi.fn(), patch: vi.fn(), put: vi.fn(), delete: vi.fn() },
}));
vi.mock("next/navigation", async (importOriginal) => ({
  ...(await importOriginal<typeof import("next/navigation")>()),
  usePathname: () => "/evals",
  useRouter: () => ({ push }),
}));
vi.mock("@/hooks/use-permissions", () => ({
  usePermissions: () => ({
    can: (perm: string) => granted.perms.includes(perm),
    isLoading: false,
  }),
}));

function wrapper({ children }: { children: ReactNode }) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

function answer(runs: { items: unknown[]; total: number }) {
  get.mockImplementation((url: string) =>
    Promise.resolve(
      url.startsWith("/eval-runs/recent")
        ? runs
        : { items: [{ id: "agent-1", name: "Refund desk" }], total: 1 },
    ),
  );
}

describe("the eval runs page", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    granted.perms = [Perm.runsView, Perm.agentsView];
  });

  it("lists the runs by agent, a page at a time", async () => {
    answer({ items: [evalRun({ id: "run-1" })], total: 45 });
    render(<EvalRunsPage />, { wrapper });

    expect(await screen.findByRole("link", { name: /Refund desk/ })).toHaveAttribute(
      "href",
      "/agents/agent-1/evals/run-1",
    );
    expect(get).toHaveBeenCalledWith("/eval-runs/recent?skip=0&limit=20");
    expect(screen.getByRole("link", { name: "Dashboard" })).toHaveAttribute("href", "/dashboard");

    await userEvent.click(screen.getByRole("button", { name: "Next page" }));
    expect(get).toHaveBeenCalledWith("/eval-runs/recent?skip=20&limit=20");
  });

  it("says what an eval is, and where to start one, when there is none", async () => {
    answer({ items: [], total: 0 });
    render(<EvalRunsPage />, { wrapper });

    expect(await screen.findByText("No eval runs yet")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Open datasets" }));
    expect(push).toHaveBeenCalledWith("/datasets");
  });

  it("reads nothing for whoever may not view runs", () => {
    granted.perms = [Perm.agentsView];
    answer({ items: [], total: 0 });
    render(<EvalRunsPage />, { wrapper });

    expect(screen.getByText("You can't see eval runs")).toBeInTheDocument();
    expect(get).not.toHaveBeenCalledWith(expect.stringContaining("/eval-runs/recent"));
  });
});
