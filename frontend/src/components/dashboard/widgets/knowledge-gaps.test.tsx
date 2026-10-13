import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { TooltipProvider } from "@/components/ui";
import type { Period } from "@/lib/dashboard/period";
import { KnowledgeGapsWidget } from "./knowledge-gaps";

const useKnowledgeGapsMock = vi.fn();
vi.mock("@/hooks/use-knowledge-gaps", () => ({
  useKnowledgeGaps: (...args: unknown[]) => useKnowledgeGapsMock(...args),
}));

const PERIOD: Period = { preset: "30d", from: "2026-09-13", to: "2026-10-13" };

function widget() {
  return render(
    <TooltipProvider>
      <KnowledgeGapsWidget title="Knowledge gaps" hint="Misses" period={PERIOD} seeAll="/rag" />
    </TooltipProvider>,
  );
}

function answer(overrides: Record<string, unknown>) {
  useKnowledgeGapsMock.mockReturnValue({
    topics: [],
    isLoading: false,
    error: null,
    refetch: vi.fn(),
    ...overrides,
  });
}

describe("KnowledgeGapsWidget", () => {
  beforeEach(() => vi.clearAllMocks());

  it("lists the open topics asked most, each opening its collection's gaps tab", () => {
    answer({
      topics: [
        {
          id: "t1",
          knowledge_base_id: "kb1",
          knowledge_base_name: "Handbook",
          label: "parental leave",
          question_count: 6,
        },
      ],
    });
    widget();
    expect(useKnowledgeGapsMock).toHaveBeenCalledWith(
      { kind: "organization" },
      { status: "open", limit: 5 },
    );
    expect(screen.getByRole("link", { name: /parental leave/ })).toHaveAttribute(
      "href",
      "/rag/kb1?tab=gaps",
    );
    expect(screen.getByText("Handbook")).toBeInTheDocument();
    expect(screen.getByText("asked 6 times")).toBeInTheDocument();
  });

  it("says what appears here when there is nothing yet", () => {
    answer({});
    widget();
    expect(screen.getByText("No knowledge gaps")).toBeInTheDocument();
  });

  it("offers a retry when the listing failed, rather than an empty card", async () => {
    const refetch = vi.fn();
    answer({ error: new Error("502"), refetch });
    widget();
    expect(screen.queryByText("No knowledge gaps")).toBeNull();
    await userEvent.click(screen.getByRole("button", { name: /retry/i }));
    expect(refetch).toHaveBeenCalled();
  });

  it("shows a skeleton while loading", () => {
    answer({ isLoading: true });
    widget();
    expect(screen.queryByText("No knowledge gaps")).toBeNull();
  });
});
