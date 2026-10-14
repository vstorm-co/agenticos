import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { DEFAULT_SCORING } from "@/lib/scoring";
import type { Dataset } from "@/types/datasets";
import { DatasetCard } from "./dataset-card";

const DATASET: Dataset = {
  id: "d1",
  name: "refunds",
  description: "Questions about returns",
  visibility: "private",
  owner_user_id: null,
  latest_version: 3,
  case_count: 12,
  can_edit: true,
  scoring: DEFAULT_SCORING,
  stats: {
    with_reference: 0,
    with_counter_example: 0,
    with_tool_calls: 0,
    with_checks: 0,
    by_source: { manual: 0, import: 0, conversation: 0, synthetic: 0 },
    top_tags: [],
  },
  created_at: "2026-10-13T00:00:00Z",
  updated_at: null,
};

describe("DatasetCard", () => {
  it("links to the dataset and shows its size and version", async () => {
    const onDelete = vi.fn();
    render(<DatasetCard dataset={DATASET} onDelete={onDelete} />);
    expect(screen.getByRole("link")).toHaveAttribute("href", "/datasets/d1");
    expect(screen.getByText("v3")).toBeInTheDocument();
    expect(screen.getByText("12 cases")).toBeInTheDocument();
    expect(screen.getByText("Questions about returns")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Delete refunds" }));
    expect(onDelete).toHaveBeenCalled();
  });

  it("shows no version before a case exists, and no delete to a reader", () => {
    render(
      <DatasetCard
        dataset={{
          ...DATASET,
          latest_version: 0,
          case_count: 0,
          description: null,
          can_edit: false,
        }}
        onDelete={vi.fn()}
      />,
    );
    expect(screen.queryByText("v0")).toBeNull();
    expect(screen.queryByRole("button")).toBeNull();
  });
});
