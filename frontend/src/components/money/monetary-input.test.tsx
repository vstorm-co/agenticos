import { useState } from "react";
import { act, fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { CurrencyProvider } from "@/components/providers/currency-provider";
import { useMonetaryInputs } from "@/hooks/use-monetary-inputs";
import type { CurrencyContext } from "@/lib/currency-api";
import * as intl from "next-intl";
import { useOrgStore } from "@/stores";
import { MonetaryInput } from "./monetary-input";

let context: CurrencyContext | undefined;
vi.mock("@/hooks/use-currencies", () => ({ useCurrencies: () => ({ data: context }) }));
const save = vi.fn();
function Form({
  maxUsd,
  initialValue = "25",
  placeholder,
  positive = false,
  retainInvalid = false,
}: {
  maxUsd?: string;
  initialValue?: string;
  placeholder?: string;
  positive?: boolean;
  retainInvalid?: boolean;
} = {}) {
  const monetary = useMonetaryInputs();
  const [value, setValue] = useState(initialValue);
  const [error, setError] = useState(false);
  return (
    <>
      <label htmlFor="budget">Budget</label>
      <MonetaryInput
        id="budget"
        field="budget_usd"
        monetary={monetary}
        maxUsd={maxUsd}
        placeholder={placeholder}
        positive={positive}
        onInvalidValueChange={retainInvalid ? setValue : undefined}
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
  expect(save).toHaveBeenCalledWith({ budget_usd: "50" });
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
  expect(save).toHaveBeenCalledWith({ budget_usd: "25" });
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
  expect(save).toHaveBeenCalledWith({ budget_usd: "50" });
});

afterEach(() => vi.restoreAllMocks());
it("uses the reader's locale in the rendered monetary control", async () => {
  vi.spyOn(intl, "useLocale").mockReturnValue("pl");
  render(form());
  const input = screen.getByLabelText("Budget");
  await userEvent.clear(input);
  await userEvent.type(input, "100,5");
  expect(input).toHaveValue("100,5");
  await userEvent.click(screen.getByText("Save"));
  expect(save).toHaveBeenCalledWith({
    budget_usd: "25.125",
    monetary_inputs: { budget_usd: { amount: "100.5", currency: "PLN" } },
  });
});

it.each(["loading", "missing quote"] as const)(
  "never presents a known 5 USD cap as uncapped while %s",
  async (state) => {
    context = state === "loading" ? undefined : { ...context!, reporting_units_per_usd: null };
    const view = render(
      <CurrencyProvider>
        <Form initialValue="5" placeholder="No limit" />
      </CurrencyProvider>,
    );
    const input = screen.getByLabelText("Budget");
    expect(input).toBeDisabled();
    expect(input).toHaveValue("");
    expect(input).not.toHaveAttribute("placeholder", "No limit");
    expect(input).toHaveAttribute(
      "placeholder",
      state === "loading" ? "Loading..." : "PLN (exchange rate unavailable)",
    );
    await userEvent.click(screen.getByText("Save"));
    expect(save).toHaveBeenLastCalledWith({ budget_usd: "5" });
    context = {
      currency: "PLN",
      default_currency: "PLN",
      inherited: true,
      reporting_units_per_usd: "4",
      rates: { USD: "1", PLN: "4" },
    };
    view.rerender(
      <CurrencyProvider>
        <Form initialValue="5" placeholder="No limit" />
      </CurrencyProvider>,
    );
    expect(input).toBeEnabled();
    expect(input).toHaveValue("20");
    await userEvent.click(screen.getByText("Save"));
    expect(save).toHaveBeenLastCalledWith({ budget_usd: "5" });
  },
);

it("keeps the caller's uncapped placeholder for a genuinely empty available limit", () => {
  render(
    <CurrencyProvider>
      <Form initialValue="" placeholder="No limit" />
    </CurrencyProvider>,
  );
  const input = screen.getByLabelText("Budget");
  expect(input).toBeEnabled();
  expect(input).toHaveValue("");
  expect(input).toHaveAttribute("placeholder", "No limit");
});

it("distinguishes an invalid zero cap from a genuinely cleared limit", async () => {
  render(
    <CurrencyProvider>
      <Form initialValue="5" placeholder="No limit" positive retainInvalid />
    </CurrencyProvider>,
  );
  const input = screen.getByLabelText("Budget");
  fireEvent.change(input, { target: { value: "0" } });
  fireEvent.blur(input);
  expect(input).toHaveValue("0");
  expect(input).toBeInvalid();
  expect(screen.getByText("Enter an amount greater than zero.")).toBeVisible();
  await userEvent.click(screen.getByText("Save"));
  expect(save).not.toHaveBeenCalled();
  fireEvent.change(input, { target: { value: "" } });
  fireEvent.blur(input);
  expect(input).toBeValid();
  expect(input).toHaveAttribute("placeholder", "No limit");
});
