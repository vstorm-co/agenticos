import { useState } from "react";
import { act, fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, expect, it, vi } from "vitest";
import { CurrencyProvider } from "@/components/providers/currency-provider";
import { useMonetaryInputs } from "@/hooks/use-monetary-inputs";
import type { CurrencyContext } from "@/lib/currency-api";
import { useOrgStore } from "@/stores";
import { MonetaryInput } from "./monetary-input";

let context: CurrencyContext | undefined;
vi.mock("@/hooks/use-currencies", () => ({ useCurrencies: () => ({ data: context }) }));
const save = vi.fn();
function Form({ maxUsd }: { maxUsd?: string } = {}) {
  const monetary = useMonetaryInputs();
  const [value, setValue] = useState("25");
  const [error, setError] = useState(false);
  return (
    <>
      <label htmlFor="budget">Budget</label>
      <MonetaryInput
        id="budget"
        field="budget_usd"
        monetary={monetary}
        maxUsd={maxUsd}
        value={value}
        onValueChange={setValue}
      />
      <button
        onClick={() => {
          try {
            save(monetary.payload({ budget_usd: value }));
          } catch {
            setError(true);
          }
        }}
      >
        Save
      </button>
      <button onClick={monetary.reset}>Discard</button>
      {error && <p role="alert">Invalid amount</p>}
    </>
  );
}
const form = () => (
  <CurrencyProvider>
    <Form />
  </CurrencyProvider>
);
beforeEach(() => {
  save.mockReset();
  useOrgStore.setState({ activeOrgId: "org-a" });
  context = {
    currency: "PLN",
    default_currency: "PLN",
    inherited: true,
    reporting_units_per_usd: "4",
    rates: { USD: "1", PLN: "9" },
  };
});
it("edits exact reporting units and explicitly submits canonical USD plus its original declaration", async () => {
  render(form());
  const input = screen.getByLabelText("Budget");
  expect(input).toHaveValue("100");
  expect(input).toHaveAttribute("inputmode", "decimal");
  await userEvent.clear(input);
  await userEvent.type(input, "400.0000004");
  expect(input).toHaveValue("400.0000004");
  await userEvent.click(screen.getByText("Save"));
  expect(save).toHaveBeenCalledWith({
    budget_usd: "100",
    monetary_inputs: { budget_usd: { amount: "400.0000004", currency: "PLN" } },
  });
});
it("invalid text never silently saves the last valid limit", async () => {
  render(form());
  fireEvent.change(screen.getByLabelText("Budget"), { target: { value: "not an amount" } });
  fireEvent.blur(screen.getByLabelText("Budget"));
  expect(screen.getByLabelText("Budget")).toBeInvalid();
  await userEvent.click(screen.getByText("Save"));
  expect(save).not.toHaveBeenCalled();
  expect(screen.getByText("Invalid amount")).toBeVisible();
  expect(screen.getByLabelText("Budget")).toHaveAccessibleDescription(
    "Enter a valid non-negative amount in the reporting currency.",
  );
});
it("an explicit currency change keeps accounting USD and clears stale draft declarations", async () => {
  const view = render(form());
  fireEvent.change(screen.getByLabelText("Budget"), { target: { value: "200" } });
  context = { ...context!, currency: "EUR", reporting_units_per_usd: "0.9" };
  view.rerender(form());
  expect(screen.getByLabelText("Budget")).toHaveValue("45");
  await userEvent.click(screen.getByText("Save"));
  expect(save).toHaveBeenCalledWith({ budget_usd: "50", monetary_inputs: {} });
});
it("a missing reporting quote disables entry instead of assuming one-to-one USD", () => {
  context = { ...context!, reporting_units_per_usd: null };
  render(form());
  expect(screen.getByLabelText("Budget")).toBeDisabled();
});

it("discard restores the canonical amount and clears native invalidity and declarations", async () => {
  render(form());
  const input = screen.getByLabelText("Budget");
  fireEvent.change(input, { target: { value: "invalid" } });
  fireEvent.blur(input);
  expect(input).toBeInvalid();
  await userEvent.click(screen.getByText("Discard"));
  expect(input).toHaveValue("100");
  expect(input).toBeValid();
  await userEvent.click(screen.getByText("Save"));
  expect(save).toHaveBeenCalledWith({ budget_usd: "25", monetary_inputs: {} });
});
it("checks a USD boundary in the visible currency and refuses the original write", async () => {
  render(
    <CurrencyProvider>
      <Form maxUsd="30" />
    </CurrencyProvider>,
  );
  const input = screen.getByLabelText("Budget");
  fireEvent.change(input, { target: { value: "121" } });
  fireEvent.blur(input);
  expect(input).toBeInvalid();
  expect(input).toHaveAccessibleDescription("Enter at most 120 PLN.");
  await userEvent.click(screen.getByText("Save"));
  expect(save).not.toHaveBeenCalled();
});

it("changing organization clears original declarations even with the same reporting quote", async () => {
  render(form());
  fireEvent.change(screen.getByLabelText("Budget"), { target: { value: "200" } });
  act(() => useOrgStore.setState({ activeOrgId: "org-b" }));
  await userEvent.click(screen.getByText("Save"));
  expect(save).toHaveBeenCalledWith({ budget_usd: "50", monetary_inputs: {} });
});
