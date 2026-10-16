import { fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { TooltipProvider } from "@/components/ui";
import type { Period } from "@/lib/dashboard/period";
import type { VisualListItem } from "@/lib/visuals-api";
import { RecentVisualsWidget } from "./recent-visuals";

const useRecentVisualsMock = vi.fn();
vi.mock("@/hooks/use-recent-visuals", () => ({
  useRecentVisuals: (...args: unknown[]) => useRecentVisualsMock(...args),
}));

const PERIOD: Period = { preset: "30d", from: "2026-09-16", to: "2026-10-16" };

function visual(overrides: Partial<VisualListItem> = {}): VisualListItem {
  return {
    id: "v1",
    conversation_id: "c1",
    tool_call_id: "toolu_1",
    agent_id: null,
    title: "Order flow",
    kind: "svg",
    revision_of: null,
    artifact_id: null,
    has_thumbnail: true,
    created_at: "2026-10-16T10:00:00Z",
    ...overrides,
  };
}

function widget() {
  return render(
    <TooltipProvider>
      <RecentVisualsWidget title="Recent visuals" hint="Drawn lately" period={PERIOD} />
    </TooltipProvider>,
  );
}

describe("RecentVisualsWidget", () => {
  beforeEach(() => vi.clearAllMocks());

  it("shows each drawing as a tile that opens its conversation", () => {
    useRecentVisualsMock.mockReturnValue({
      visuals: [
        visual(),
        visual({
          id: "v2",
          title: "Explainer",
          kind: "html",
          has_thumbnail: false,
          artifact_id: "a",
        }),
      ],
      isLoading: false,
      error: null,
      refetch: vi.fn(),
    });
    widget();

    expect(useRecentVisualsMock).toHaveBeenCalledWith(6);
    expect(screen.getByRole("link", { name: /Order flow/ })).toHaveAttribute("href", "/chat?id=c1");
    // A page with none kept yet is asked for too: asking is what draws it.
    const thumbnails = [...document.querySelectorAll("img")].map((img) => img.getAttribute("src"));
    expect(thumbnails).toEqual(["/api/visuals/v1/thumbnail", "/api/visuals/v2/thumbnail"]);
    expect(screen.getByText("App")).toBeInTheDocument();
  });

  it("shows the kind's mark for a diagram with no thumbnail yet", () => {
    useRecentVisualsMock.mockReturnValue({
      visuals: [visual({ kind: "mermaid", has_thumbnail: false })],
      isLoading: false,
      error: null,
      refetch: vi.fn(),
    });
    widget();
    expect(document.querySelector("img")).toBeNull();
  });

  it("falls back to the kind's mark when the thumbnail will not load", () => {
    useRecentVisualsMock.mockReturnValue({
      visuals: [visual()],
      isLoading: false,
      error: null,
      refetch: vi.fn(),
    });
    widget();
    fireEvent.error(document.querySelector("img")!);
    expect(document.querySelector("img")).toBeNull();
  });

  it("says how to get one when nothing has been drawn", () => {
    useRecentVisualsMock.mockReturnValue({
      visuals: [],
      isLoading: false,
      error: null,
      refetch: vi.fn(),
    });
    widget();
    expect(screen.getByText("Nothing drawn yet")).toBeInTheDocument();
  });

  it("offers a retry when the listing failed, rather than an empty card", async () => {
    const refetch = vi.fn();
    useRecentVisualsMock.mockReturnValue({
      visuals: [],
      isLoading: false,
      error: new Error("502"),
      refetch,
    });
    widget();
    await userEvent.click(screen.getByRole("button", { name: /retry/i }));
    expect(refetch).toHaveBeenCalled();
  });

  it("holds its place while loading", () => {
    useRecentVisualsMock.mockReturnValue({
      visuals: [],
      isLoading: true,
      error: null,
      refetch: vi.fn(),
    });
    widget();
    expect(screen.queryByText("Nothing drawn yet")).toBeNull();
  });
});
