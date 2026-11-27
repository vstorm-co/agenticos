import { render, screen } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";
import type { CurrencyContext } from "@/lib/currency-api";
import { CurrencyProvider, useMoney } from "./currency-provider";
import { MessageCost, RoundedCost } from "@/components/chat/message-cost";
import { AnimatedAmount } from "@/components/ui/animated-number";
import type { TurnUsage } from "@/types";

let context: CurrencyContext | undefined;
vi.mock("@/hooks/use-currencies", () => ({ useCurrencies: () => ({ data: context }) }));

function Reading() {
  const money = useMoney();
  return <output>{money.format("2", "en")}</output>;
}
const usage: TurnUsage = {
  input_tokens: 4,
  output_tokens: 2,
  cost_usd: "0.001",
  cost_is_partial: false,
  budget_percent: null,
  agent_budget_percent: null,
  sandbox: null,
  context: null,
};

beforeEach(() => {
  context = {
    currency: "PLN",
    default_currency: "USD",
    inherited: false,
    rates: { USD: "1", PLN: "4" },
  };
});

it("updates all visible readings when the active organization changes", () => {
  const view = render(
    <CurrencyProvider>
      <Reading />
    </CurrencyProvider>,
  );
  expect(screen.getByText(/PLN.*8.00/)).toBeVisible();
  context = { ...context!, currency: "EUR", rates: { USD: "1", EUR: "0.9" } };
  view.rerender(
    <CurrencyProvider>
      <Reading />
    </CurrencyProvider>,
  );
  expect(screen.getByText(/EUR.*1.80/)).toBeVisible();
  expect(screen.queryByText(/PLN/)).not.toBeInTheDocument();
  context = undefined;
  view.rerender(
    <CurrencyProvider>
      <Reading />
    </CurrencyProvider>,
  );
  expect(screen.getByText("—")).toBeVisible();
});

it("retains USD for public readings outside a workspace", () => {
  render(<Reading />);
  expect(screen.getByText("$2.00")).toBeVisible();
});

it("uses the organization currency in chat costs and animated totals", () => {
  render(
    <CurrencyProvider>
      <MessageCost usage={usage} />
      <RoundedCost usage={usage} />
      <AnimatedAmount value="2" label="total" />
    </CurrencyProvider>,
  );
  expect(screen.getByText(/PLN.*0.0040/)).toBeVisible();
  expect(screen.getByText(/< PLN.*0.01/)).toBeVisible();
  expect(screen.getByLabelText("total")).toHaveTextContent(/PLN.*8.00/);
});
