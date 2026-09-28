import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { TooltipProvider } from "@/components/ui";
import type { Period } from "@/lib/dashboard/period";
import { ArtifactsWidget } from "./artifacts";

const useArtifactsMock = vi.fn();
vi.mock("@/hooks/use-artifacts", () => ({
  useArtifacts: (...args: unknown[]) => useArtifactsMock(...args),
}));

const PERIOD: Period = { preset: "30d", from: "2026-08-23", to: "2026-09-22" };

function widget() {
  return render(
    <TooltipProvider>
      <ArtifactsWidget title="Artifacts" hint="Recent pages" period={PERIOD} seeAll="/artifacts" />
    </TooltipProvider>,
  );
}

describe("ArtifactsWidget", () => {
  beforeEach(() => vi.clearAllMocks());

  it("lists the most recently published pages, each a link", () => {
    useArtifactsMock.mockReturnValue({
      artifacts: [
        { id: "a1", title: "Weekly report", published_at: "2026-09-22T10:00:00Z" },
        { id: "a2", title: "Churn dashboard", published_at: "2026-09-20T10:00:00Z" },
      ],
      isLoading: false,
      error: null,
      refetch: vi.fn(),
    });
    widget();
    expect(useArtifactsMock).toHaveBeenCalledWith({ limit: 5 });
    expect(screen.getByRole("link", { name: /Weekly report/ })).toHaveAttribute(
      "href",
      "/artifacts/a1",
    );
    expect(screen.getByRole("link", { name: /Churn dashboard/ })).toBeInTheDocument();
  });

  it("says where a page comes from when there is none", () => {
    useArtifactsMock.mockReturnValue({
      artifacts: [],
      isLoading: false,
      error: null,
      refetch: vi.fn(),
    });
    widget();
    expect(screen.getByText("Nothing published yet")).toBeInTheDocument();
  });

  it("offers a retry when the listing failed, rather than an empty card", async () => {
    const refetch = vi.fn();
    useArtifactsMock.mockReturnValue({
      artifacts: [],
      isLoading: false,
      error: new Error("502"),
      refetch,
    });
    widget();
    expect(screen.queryByText("Nothing published yet")).toBeNull();
    await userEvent.click(screen.getByRole("button", { name: /retry/i }));
    expect(refetch).toHaveBeenCalled();
  });

  it("shows a skeleton while loading", () => {
    useArtifactsMock.mockReturnValue({
      artifacts: [],
      isLoading: true,
      error: null,
      refetch: vi.fn(),
    });
    widget();
    expect(screen.queryByText("Nothing published yet")).toBeNull();
    expect(screen.queryByRole("link", { name: /Weekly/ })).toBeNull();
  });
});
