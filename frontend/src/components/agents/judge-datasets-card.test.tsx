import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { JudgeDatasetsCard } from "./judge-datasets-card";

const state = vi.hoisted(() => ({
  result: {
    datasets: [] as { id: string; name: string }[],
    isLoading: false,
    error: null as Error | null,
  },
}));
vi.mock("@/hooks/use-datasets", () => ({ useDatasets: () => state.result }));
const agreement = vi.hoisted(() => ({
  value: undefined as { agreed: number; decided: number } | undefined,
}));
vi.mock("@/hooks/use-scoring", () => ({
  useJudgeAgreement: () => ({ agreement: agreement.value, isLoading: false }),
}));

beforeEach(() => {
  state.result = { datasets: [], isLoading: false, error: null };
  agreement.value = undefined;
});

describe("JudgeDatasetsCard", () => {
  it("links each dataset the judge grades to its Grading tab", () => {
    state.result.datasets = [{ id: "d1", name: "Refunds" }];
    render(<JudgeDatasetsCard judgeId="j1" />);

    expect(screen.getByRole("link", { name: "Refunds" })).toHaveAttribute(
      "href",
      "/datasets/d1?tab=grading",
    );
  });

  it("says when no dataset uses the judge", () => {
    render(<JudgeDatasetsCard judgeId="j1" />);

    expect(screen.getByText("No dataset uses this judge yet.")).toBeInTheDocument();
  });

  it("says why the datasets could not be read, and waits while they load", () => {
    state.result.error = new Error("Datasets are unreachable");
    const { rerender } = render(<JudgeDatasetsCard judgeId="j1" />);
    expect(screen.getByText("Datasets are unreachable")).toBeInTheDocument();

    state.result = { datasets: [], isLoading: true, error: null };
    rerender(<JudgeDatasetsCard judgeId="j1" />);
    expect(screen.queryByText("No dataset uses this judge yet.")).toBeNull();
  });

  it("says how often people agreed with the judge, once anybody decided", () => {
    const { rerender } = render(<JudgeDatasetsCard judgeId="j1" />);
    expect(screen.queryByText(/agreed with this judge/)).toBeNull();

    agreement.value = { agreed: 0, decided: 0 };
    rerender(<JudgeDatasetsCard judgeId="j1" />);
    expect(screen.getByText(/Nobody has decided a result this judge graded/)).toBeInTheDocument();

    agreement.value = { agreed: 7, decided: 10 };
    rerender(<JudgeDatasetsCard judgeId="j1" />);
    expect(
      screen.getByText("People agreed with this judge on 7 of 10 results they decided."),
    ).toBeInTheDocument();
  });
});
