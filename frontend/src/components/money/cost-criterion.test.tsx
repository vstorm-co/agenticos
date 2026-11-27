import { render, screen } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";
import { CurrencyProvider } from "@/components/providers/currency-provider";
import type { CurrencyContext } from "@/lib/currency-api";
import type { ScorerResult } from "@/types/scoring";
import { CostCriterionName, CostCriterionReason } from "./cost-criterion";

let context: CurrencyContext;
vi.mock("@/hooks/use-currencies", () => ({ useCurrencies: () => ({ data: context }) }));
const result: ScorerResult = {
  scorer: "check",
  name: "cost <= $25",
  required: true,
  status: "fail",
  score: 0,
  reason: "Canonical USD evidence",
  reason_code: null,
  unverified_quotes: [],
  rule: null,
  unverified: false,
  judge_said: null,
  judge_run_id: null,
  knowledge: [],
  cost_limit_usd: "25",
  cost_observed_usd: "26",
};
beforeEach(() => {
  context = {
    currency: "PLN",
    default_currency: "PLN",
    inherited: true,
    reporting_units_per_usd: "4",
    rates: { USD: "1", PLN: "9" },
  };
});
it("reports structured cost criteria with the same frozen quote as budget utilization", () => {
  render(
    <CurrencyProvider>
      <p>
        <CostCriterionName result={result} />
      </p>
      <p>
        <CostCriterionReason result={result} fallback={result.reason} />
      </p>
    </CurrencyProvider>,
  );
  expect(screen.getByText("Cost ≤ PLN 100.00")).toBeVisible();
  expect(screen.getByText("Observed PLN 104.00; limit PLN 100.00.")).toBeVisible();
  expect(result.name).toBe("cost <= $25");
});
it("keeps old canonical criterion identities and non-monetary explanations unchanged", () => {
  const old = { ...result, cost_limit_usd: null, cost_observed_usd: null };
  render(
    <CurrencyProvider>
      <p>
        <CostCriterionName result={old} />
      </p>
      <p>
        <CostCriterionReason result={old} fallback={old.reason} />
      </p>
    </CurrencyProvider>,
  );
  expect(screen.getByText(old.name)).toBeVisible();
  expect(screen.getByText(old.reason)).toBeVisible();
});
it("missing reporting FX is unavailable rather than a free cost criterion", () => {
  context = { ...context, reporting_units_per_usd: null };
  render(
    <CurrencyProvider>
      <p>
        <CostCriterionName result={result} />
      </p>
      <p>
        <CostCriterionReason result={result} fallback={result.reason} />
      </p>
    </CurrencyProvider>,
  );
  expect(screen.getByText("Cost ≤ —")).toBeVisible();
  expect(screen.getByText("Observed —; limit —.")).toBeVisible();
});

it("an unmeasured attempt retains its translated explanation rather than inventing zero cost", () => {
  render(
    <CurrencyProvider>
      <CostCriterionReason
        result={{ ...result, cost_observed_usd: null }}
        fallback="Cost was not measured"
      />
    </CurrencyProvider>,
  );
  expect(screen.getByText("Cost was not measured")).toBeVisible();
});
