import { render, screen, within } from "@testing-library/react";
import { expect, it } from "vitest";
import { SESSION } from "@/test-utils/improvement";
import type { ImprovementIteration, VerdictCriterion } from "@/types/improvement";
import { CriteriaNote, CriteriaTable, criteriaOf } from "./criteria";

const PRICE_BREAK: VerdictCriterion = {
  scorer: "judge",
  name: "price break",
  graded: 40,
  before: 9,
  after: 40,
  fixed: 31,
  broken: 0,
};
const failing = (name: string, skill?: string): VerdictCriterion => ({
  scorer: "judge",
  name,
  graded: 40,
  before: 0,
  after: 0,
  fixed: 0,
  broken: 0,
  skill,
});
const LENGTH: VerdictCriterion = {
  scorer: "check",
  name: "under 200 words",
  graded: 40,
  before: 40,
  after: 30,
  fixed: 0,
  broken: 10,
};

const attempt = (
  verdict: ImprovementIteration["verdict"],
  criteria: VerdictCriterion[],
): ImprovementIteration => ({
  ...SESSION.iterations[0]!,
  number: 1,
  verdict,
  verdict_detail: { fixed: 0, broken: 0, criteria },
});

it("says which criterion an attempt fixed and which still keep every question failing", () => {
  const round = attempt("criteria_better", [
    PRICE_BREAK,
    failing("validity", "Quote rules"),
    failing("payment terms", "Quote rules"),
  ]);

  render(<CriteriaNote round={round} agent="Quote Builder" />);

  expect(
    screen.getByText(
      "Attempt 1 made Quote Builder better on 1 criterion: price break 9/40 → 40/40. " +
        "No additional question passes yet, because other criteria still fail: " +
        "validity (skill “Quote rules”) and payment terms (skill “Quote rules”).",
    ),
  ).toBeInTheDocument();
  expect(screen.queryByText(/no change/i)).not.toBeInTheDocument();
});

it("names a criterion that got worse as plainly as one that got better", () => {
  render(
    <CriteriaNote round={attempt("criteria_worse", [PRICE_BREAK, LENGTH])} agent="Quote Builder" />,
  );

  expect(
    screen.getByText(
      "Attempt 1 made Quote Builder worse on 1 criterion, though no question broke: " +
        "under 200 words 40/40 → 30/40.",
    ),
  ).toBeInTheDocument();
});

it("adds a criterion that got worse to an attempt that fixed whole questions", () => {
  render(<CriteriaNote round={attempt("better", [LENGTH])} agent="Quote Builder" />);

  expect(
    screen.getByText(
      "Attempt 1 also made Quote Builder worse on 1 criterion: under 200 words 40/40 → 30/40.",
    ),
  ).toBeInTheDocument();
});

it("counts the still-failing criteria past the first five rather than naming them all", () => {
  const many = ["a", "b", "c", "d", "e", "f", "g"].map((name) => failing(name));
  const { container } = render(
    <CriteriaNote round={attempt("criteria_better", [PRICE_BREAK, ...many])} agent="Desk" />,
  );

  expect(container).toHaveTextContent("still fail: a, b, c, d, e, and 2 more.");
});

it.each(["no_change", "criteria_better"] as const)(
  "says nothing for a %s attempt whose criteria did not move",
  (verdict) => {
    const { container } = render(
      <CriteriaNote round={attempt(verdict, [failing("validity")])} agent="Desk" />,
    );

    expect(container).toBeEmptyDOMElement();
  },
);

it("reads no criteria from an attempt measured before they were kept", () => {
  expect(criteriaOf({ ...SESSION.iterations[0]!, verdict_detail: { fixed: 1 } })).toEqual([]);
  expect(criteriaOf(undefined)).toEqual([]);
});

it("tables every criterion with its passes before and after and what the reruns confirmed", () => {
  const both = { ...LENGTH, name: "tone", fixed: 2, broken: 1 };
  render(
    <CriteriaTable criteria={[PRICE_BREAK, LENGTH, both, failing("validity", "Quote rules")]} />,
  );

  const rows = screen.getAllByRole("row").slice(1);
  expect(rows.map((row) => row.textContent)).toEqual([
    "price break9 of 4040 of 40+31 fixed",
    "under 200 words40 of 4030 of 4010 broken",
    "tone40 of 4030 of 40+2 fixed · 1 broken",
    "validityPut down to the skill “Quote rules”0 of 400 of 40None",
  ]);
  expect(within(rows[3]!).getByText("Put down to the skill “Quote rules”")).toBeInTheDocument();
});

it("draws no table for a change with no criteria", () => {
  const { container } = render(<CriteriaTable criteria={[]} />);

  expect(container).toBeEmptyDOMElement();
});

it("says no more than what moved when no criterion is left failing", () => {
  render(<CriteriaNote round={attempt("criteria_better", [PRICE_BREAK])} agent="Desk" />);

  expect(
    screen.getByText("Attempt 1 made Desk better on 1 criterion: price break 9/40 → 40/40."),
  ).toBeInTheDocument();
});

it("does not label a confirmed fix as better when its total passes declined", () => {
  const declined = { ...PRICE_BREAK, name: "net decline", before: 30, after: 20, fixed: 1 };
  render(
    <CriteriaNote
      round={attempt("criteria_better", [PRICE_BREAK, declined])}
      agent="Quote Builder"
    />,
  );
  expect(screen.getByText(/better on 1 criterion: price break/)).toBeVisible();
  expect(screen.queryByText(/better on 2 criteria/)).not.toBeInTheDocument();
});

it("displays scorer identity for duplicate names in tables and result sentences", () => {
  const criteria = [
    { ...PRICE_BREAK, name: "Validity" },
    { ...failing("Validity"), scorer: "check" },
  ];
  render(
    <>
      <CriteriaTable criteria={criteria} />
      <CriteriaNote round={attempt("criteria_better", criteria)} agent="Clerk" />
    </>,
  );
  expect(screen.getByRole("cell", { name: "Validity [judge]" })).toBeVisible();
  expect(screen.getByRole("cell", { name: "Validity [check]" })).toBeVisible();
  const sentence = document.querySelector("p");
  expect(sentence).toHaveTextContent("Validity [judge]");
  expect(sentence).toHaveTextContent("Validity [check]");
});
