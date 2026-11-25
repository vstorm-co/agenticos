import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, expect, it, vi } from "vitest";
import { SESSION } from "@/test-utils/improvement";
import { ApiError } from "@/lib/api-error";
import type { Improvement, SearchVariant, VariantSearch as Search } from "@/types/improvement";
import { VariantSearch } from "./variant-search";

const choose = vi.hoisted(() => vi.fn());
vi.mock("@/hooks/use-improvements", () => ({
  useImprovement: () => ({ chooseVariant: { mutateAsync: choose, isPending: false } }),
}));

const variant = (id: string, score: number, rationale = ""): SearchVariant => ({
  id,
  generation: 1,
  parent_id: null,
  status: "scored",
  train_score: score,
  cases_scored: 12,
  cases_passed: 10,
  cost_usd: "0.12",
  rationale,
  instructions: `Instructions ${id}`,
});

const SEARCH: Search = {
  budget_usd: "3",
  cost_usd: "1.25",
  grading_model_profile_id: null,
  max_variants: 40,
  per_generation: 4,
  patience: 3,
  questions: 12,
  generation: 2,
  tried: 9,
  pending: 0,
  seed_score: 0.5,
  best_score: 0.75,
  stop_reason: "patience",
  chosen_variant_id: "v1",
  top: [variant("v1", 0.75, "Names the refund window"), variant("v2", 0.7)],
};

function at(search: Search | null): Improvement {
  return {
    ...SESSION,
    status: "waiting",
    stage: "filtering",
    iterations: [{ ...SESSION.iterations[0]!, eval_run_ids: [], variant_search: search }],
  };
}

beforeEach(() => {
  choose.mockReset();
});

it("shows what the search tried and spent, and that its scores are not the verdict", () => {
  render(<VariantSearch session={at(SEARCH)} choosable={false} />);

  expect(
    screen.getByText("9 of up to 40 variants tried, each on the same 12 training questions."),
  ).toBeInTheDocument();
  expect(screen.getByText("Spent $1.25 of the $3.00 search budget.")).toBeInTheDocument();
  expect(
    screen.getByText("Current instructions: 50% of required checks passed · best variant: 75%."),
  ).toBeInTheDocument();
  expect(
    screen.getByText("The search stopped after rounds that found nothing better."),
  ).toBeInTheDocument();
  expect(screen.getByText(/training questions only/)).toBeInTheDocument();
  expect(screen.getByText(/at most the one variant/)).toBeInTheDocument();
  expect(screen.getByText("Names the refund window")).toBeInTheDocument();
  expect(screen.getByText("Brought to Changes")).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "Bring to Changes instead" })).toBeNull();
});

it("brings another of the best variants to Changes, and says why it could not", async () => {
  choose.mockRejectedValueOnce(new ApiError(400, "Another variant can be chosen only at Changes"));
  const user = userEvent.setup();
  render(<VariantSearch session={at(SEARCH)} choosable />);

  await user.click(screen.getByRole("button", { name: "Bring to Changes instead" }));

  expect(choose).toHaveBeenCalledWith("v2");
  expect(await screen.findByRole("alert")).toHaveTextContent("only at Changes");
  choose.mockResolvedValueOnce(at(SEARCH));
  await user.click(screen.getByRole("button", { name: "Bring to Changes instead" }));
  expect(screen.queryByRole("alert")).toBeNull();
});

it("reads a search still running, and nothing for an attempt without one", () => {
  const running = { ...SEARCH, stop_reason: null, seed_score: null, best_score: null, top: [] };
  const { container, rerender } = render(<VariantSearch session={at(running)} choosable />);
  expect(
    screen.getByText("Current instructions: — of required checks passed · best variant: —."),
  ).toBeInTheDocument();
  expect(screen.queryByRole("list")).toBeNull();

  rerender(<VariantSearch session={at(null)} choosable />);
  expect(container).toBeEmptyDOMElement();
});
