import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { TooltipProvider } from "@/components/ui";
import type { Period } from "@/lib/dashboard/period";
import { ProjectsWidget } from "./projects";

const useProjectsMock = vi.fn();
vi.mock("@/hooks/use-projects", () => ({
  useProjects: (...args: unknown[]) => useProjectsMock(...args),
}));

const PERIOD: Period = { preset: "30d", from: "2026-09-17", to: "2026-10-17" };

function widget() {
  return render(
    <TooltipProvider>
      <ProjectsWidget title="Projects" hint="Your projects" period={PERIOD} seeAll="/projects" />
    </TooltipProvider>,
  );
}

describe("ProjectsWidget", () => {
  beforeEach(() => vi.clearAllMocks());

  it("draws a tile per project, each a link with its chats and when it was active", () => {
    useProjectsMock.mockReturnValue({
      projects: [
        {
          id: "p-1",
          name: "launch",
          chat_count: 3,
          last_active_at: new Date().toISOString(),
          updated_at: null,
          created_at: null,
        },
        {
          id: "p-2",
          name: "Treasury",
          chat_count: 0,
          last_active_at: null,
          updated_at: null,
          created_at: null,
        },
      ],
      isLoading: false,
      error: null,
      refetch: vi.fn(),
    });
    widget();
    expect(useProjectsMock).toHaveBeenCalledWith({ limit: 4 });
    expect(screen.getByRole("link", { name: /launch/ })).toHaveAttribute("href", "/projects/p-1");
    expect(screen.getByText("L")).toBeInTheDocument();
    expect(screen.getByText(/3 chats ·/)).toBeInTheDocument();
    expect(screen.getByText("No chats yet")).toBeInTheDocument();
  });

  it("says what a project is when there is none", () => {
    useProjectsMock.mockReturnValue({
      projects: [],
      isLoading: false,
      error: null,
      refetch: vi.fn(),
    });
    widget();
    expect(screen.getByText("No projects yet")).toBeInTheDocument();
  });

  it("holds its place while loading, and offers a retry when the listing failed", async () => {
    useProjectsMock.mockReturnValue({
      projects: [],
      isLoading: true,
      error: null,
      refetch: vi.fn(),
    });
    const { unmount } = widget();
    expect(screen.queryByText("No projects yet")).not.toBeInTheDocument();
    unmount();

    const refetch = vi.fn();
    useProjectsMock.mockReturnValue({
      projects: [],
      isLoading: false,
      error: new Error("502"),
      refetch,
    });
    widget();
    await userEvent.click(screen.getByRole("button", { name: /retry/i }));
    expect(refetch).toHaveBeenCalled();
  });
});
