import { render, screen, within } from "@testing-library/react";
import { expect, it } from "vitest";
import { SESSION } from "@/test-utils/improvement";
import type { ImprovementIteration, VerdictCriterion, VerdictFamily } from "@/types/improvement";
import {
  criterionName,
  CriteriaNote,
  CriteriaTable,
  criteriaOf,
  criterionRows,
  familiesOf,
  familyRows,
  movedCriteria,
  rowsOf,
} from "./criteria";

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
    <CriteriaTable
      criteria={criterionRows([PRICE_BREAK, LENGTH, both, failing("validity", "Quote rules")])}
    />,
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
      <CriteriaTable criteria={criterionRows(criteria)} />
      <CriteriaNote round={attempt("criteria_better", criteria)} agent="Clerk" />
    </>,
  );
  expect(screen.getByRole("cell", { name: "Validity [judge]" })).toBeVisible();
  expect(screen.getByRole("cell", { name: "Validity [check]" })).toBeVisible();
  const sentence = document.querySelector("p");
  expect(sentence).toHaveTextContent("Validity [judge]");
  expect(sentence).toHaveTextContent("Validity [check]");
});

const family = (overrides: Partial<VerdictFamily>): VerdictFamily => ({
  family: "price break",
  criteria: 22,
  cases: 28,
  before: 3,
  after: 28,
  fixed: 25,
  broken: 0,
  settled: true,
  better: true,
  worse: false,
  ...overrides,
});
const VAT = family({
  family: "total including VAT",
  criteria: 24,
  cases: 24,
  before: 14,
  after: 7,
  fixed: 0,
  broken: 7,
  better: false,
  worse: true,
  skill: "fernhill-quote-format",
});
const withFamilies = (
  verdict: ImprovementIteration["verdict"],
  families: VerdictFamily[],
): ImprovementIteration => ({
  ...attempt(verdict, [PRICE_BREAK]),
  verdict_detail: { fixed: 0, broken: 0, criteria: [PRICE_BREAK], families },
});

it("reads an attempt by its families, question by question, when it kept them", () => {
  const round = withFamilies("criteria_better", [family({}), VAT]);

  expect(rowsOf(round).map((row) => [row.name, row.graded, row.before, row.after])).toEqual([
    ["price break", 28, 3, 28],
    ["total including VAT", 24, 14, 7],
  ]);
  expect(familiesOf(undefined)).toEqual([]);
  expect(rowsOf(attempt("criteria_better", [PRICE_BREAK]))[0]!.name).toBe("price break");
});

it("puts a family a skill gets wrong on the skill, not on the agent", () => {
  const round = withFamilies("criteria_better", [family({}), VAT]);

  const moved = movedCriteria(round);
  render(<CriteriaNote round={round} agent="Reorder Assistant" />);

  expect(moved.worse).toEqual([]);
  expect(moved.skillWorse.map((row) => row.name)).toEqual(["total including VAT"]);
  expect(
    screen.getByText(
      "Attempt 1 made Reorder Assistant better on 1 criterion: price break 3/28 → 28/28. " +
        "Reorder Assistant now follows the skill more closely and fails more often on 1 " +
        "criterion the skill gets wrong: total including VAT 14/24 → 7/24. Fix the skill " +
        "rather than the agent.",
    ),
  ).toBeInTheDocument();
});

it("says what an attempt that broke questions still made better", () => {
  render(<CriteriaNote round={withFamilies("regression", [family({})])} agent="Quote Builder" />);

  expect(
    screen.getByText(
      "Beside the questions it broke, attempt 1 made Quote Builder better on 1 criterion: " +
        "price break 3/28 → 28/28. Keep the part that helped by trying again with a note.",
    ),
  ).toBeInTheDocument();
});

it("counts an unsettled family's confirmed flips and a settled one's every flip", () => {
  const base = {
    criteria: ["a"],
    cases: 6,
    baseline_passed: 4,
    candidate_passed: 1,
    fixed: 1,
    broken: 4,
    fixed_confirmed: 0,
    broken_confirmed: 2,
    p_value: 0.375,
    better: false,
    worse: true,
  };

  const [unsettled, settled] = familyRows([
    { ...base, family: "vat", settled: false },
    { ...base, family: "terms", settled: true },
  ]);

  expect([unsettled!.fixed, unsettled!.broken]).toEqual([0, 2]);
  expect([settled!.fixed, settled!.broken]).toEqual([1, 4]);
});

it("marks a criterion name cut at the stored length, keeping its last word only when whole", () => {
  // Cut at 80 on a space and trimmed: 79 characters, the last word whole.
  const onSpace = "States that brochures take 7 working days of standard production plus 1 working";
  expect(onSpace.length).toBe(79);
  expect(criterionName(onSpace)).toBe(`${onSpace}…`);
  // Cut at 80 inside a word: the last word may be partial, so it ends at the one before.
  const midWord = `${onSpace} d`;
  expect(midWord.length).toBe(81);
  expect(criterionName(midWord.slice(0, 80))).toBe(
    "States that brochures take 7 working days of standard production plus 1 working…",
  );
  expect(criterionName("x".repeat(80))).toBe(`${"x".repeat(80)}…`);
  expect(
    criterionName(`${"A sentence written whole ".repeat(3)}and long enough to fill it.`),
  ).toMatch(/fill it\.$/);
  expect(criterionName("total including VAT")).toBe("total including VAT");
});
