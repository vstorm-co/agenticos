import { useState } from "react";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { CurrencySettingsEditor } from "./currency-settings";
import { validCurrencySettings, type CurrencySettings } from "@/lib/currency-api";

function Form({ disabled = false }: { disabled?: boolean }) {
  const [value, setValue] = useState<CurrencySettings | null>(null);
  return (
    <>
      <CurrencySettingsEditor
        value={value}
        effective={{ default_currency: "USD", rates: { USD: "1" } }}
        disabled={disabled}
        onChange={setValue}
      />
      <output data-testid="settings">{JSON.stringify(value)}</output>
    </>
  );
}

describe("manual currencies", () => {
  it("adds a currency, selects its default, edits its rate, removes it and restores environment defaults", async () => {
    const user = userEvent.setup();
    render(<Form />);
    expect(screen.getByLabelText("USD per USD")).toBeDisabled();
    expect(screen.getByRole("button", { name: "Add currency" })).toBeDisabled();
    await user.type(screen.getByLabelText("Currency code"), "eur");
    await user.type(screen.getByLabelText("Units per USD"), "0.9");
    await user.click(screen.getByRole("button", { name: "Add currency" }));
    expect(screen.getByLabelText("EUR per USD")).toHaveValue(0.9);
    await user.click(screen.getByLabelText("Default organization currency"));
    await user.click(screen.getByRole("option", { name: "EUR" }));
    expect(screen.getByRole("button", { name: "Remove EUR" })).toBeDisabled();
    await user.clear(screen.getByLabelText("EUR per USD"));
    await user.type(screen.getByLabelText("EUR per USD"), "1.1");
    expect(JSON.parse(screen.getByTestId("settings").textContent!).rates.EUR).toBe("1.1");
    await user.click(screen.getByLabelText("Default organization currency"));
    await user.click(screen.getByRole("option", { name: "USD" }));
    await user.click(screen.getByRole("button", { name: "Remove EUR" }));
    expect(screen.queryByLabelText("EUR per USD")).not.toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Use environment defaults" }));
    expect(screen.getByTestId("settings")).toHaveTextContent("null");
  });
  it("disables controls during saving", () => {
    render(<Form disabled />);
    expect(screen.getByLabelText("Currency code")).toBeDisabled();
    expect(screen.getByLabelText("Default organization currency")).toBeDisabled();
  });
  it.each<CurrencySettings>([
    { default_currency: "USD", rates: { USD: "1" } },
    { default_currency: "PLN", rates: { USD: "1", PLN: "4" } },
  ])("accepts valid settings", (value) => expect(validCurrencySettings(value)).toBe(true));
  it.each<CurrencySettings>([
    { default_currency: "EUR", rates: { USD: "1" } },
    { default_currency: "USD", rates: { USD: "2" } },
    { default_currency: "USD", rates: { USD: "1", EUR: "0" } },
    { default_currency: "USD", rates: { USD: "1", invalid: "2" } },
    { default_currency: "USD", rates: { USD: "1", EUR: "NaN" } },
    { default_currency: "USD", rates: { USD: "1", EUR: "" } },
  ])("refuses invalid settings", (value) => expect(validCurrencySettings(value)).toBe(false));
});
