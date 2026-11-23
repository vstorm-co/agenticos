import { useState } from "react";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import type { TokenPricing } from "@/types/providers";
import { ModelPricing, sameTokenPricing, validTokenPricing } from "./model-pricing";

function Form({
  automatic,
  initial = null,
  disabled = false,
}: {
  automatic?: TokenPricing | null;
  initial?: TokenPricing | null;
  disabled?: boolean;
}) {
  const [value, setValue] = useState<TokenPricing | null>(initial);
  return (
    <>
      <ModelPricing value={value} automatic={automatic} disabled={disabled} onChange={setValue} />
      <output data-testid="value">{JSON.stringify(value)}</output>
    </>
  );
}

describe("profile pricing", () => {
  it("shows unavailable automatic prices and accepts explicit zero and missing cache rates", async () => {
    const user = userEvent.setup();
    render(<Form />);
    expect(screen.getByText(/Automatic token prices are unavailable/)).toBeVisible();
    await user.click(screen.getByRole("switch"));
    await user.type(screen.getByLabelText("Input tokens"), "0");
    await user.type(screen.getByLabelText("Output tokens"), "2.5");
    await user.type(screen.getByLabelText("Cache read tokens"), "0");
    await user.type(screen.getByLabelText("Cache write tokens"), "3");
    expect(JSON.parse(screen.getByTestId("value").textContent!)).toEqual({
      input: "0",
      output: "2.5",
      cache_read: "0",
      cache_write: "3",
    });
    await user.clear(screen.getByLabelText("Cache write tokens"));
    expect(JSON.parse(screen.getByTestId("value").textContent!).cache_write).toBeNull();
    await user.click(screen.getByRole("switch"));
    expect(screen.getByTestId("value")).toHaveTextContent("null");
    expect(screen.queryByLabelText("Input tokens")).not.toBeInTheDocument();
  });

  it("displays catalog rates and starts an override from them", async () => {
    const user = userEvent.setup();
    render(<Form automatic={{ input: "2", output: "8", cache_read: "0.5" }} />);
    expect(screen.getByText(/Indicative automatic rates/)).toBeVisible();
    await user.click(screen.getByRole("switch"));
    expect(screen.getByLabelText("Input tokens")).toHaveValue(2);
    expect(screen.getByLabelText("Output tokens")).toHaveValue(8);
    expect(screen.getByLabelText("Cache read tokens")).toHaveValue(0.5);
  });

  it("preserves saved rates and disables every control when editing is unavailable", () => {
    render(<Form initial={{ input: "1", output: "2", cache_write: "0" }} disabled />);
    expect(screen.getByRole("switch")).toBeDisabled();
    expect(screen.getByLabelText("Input tokens")).toBeDisabled();
    expect(screen.getByLabelText("Cache write tokens")).toHaveValue(0);
  });

  it.each([
    null,
    { input: "0", output: "0" },
    { input: "2", output: "3", cache_read: null, cache_write: "" },
  ])("accepts complete pricing %j", (value) => expect(validTokenPricing(value)).toBe(true));
  it.each([
    { input: "", output: "0" },
    { input: " ", output: "1" },
    { input: "0", output: "NaN" },
    { input: "-1", output: "0" },
    { input: "1000001", output: "0" },
    { input: "1", output: "1", cache_read: "Infinity" },
  ])("refuses invalid pricing %j", (value) => expect(validTokenPricing(value)).toBe(false));
});

it("compares saved prices without treating omitted optional cache rates as edits", () => {
  expect(sameTokenPricing(null, null)).toBe(true);
  expect(sameTokenPricing(null, { input: "0", output: "1" })).toBe(false);
  expect(sameTokenPricing({ input: "0", output: "1" }, null)).toBe(false);
  expect(
    sameTokenPricing(
      { input: "0", output: "1" },
      { input: "0", output: "1", cache_read: null, cache_write: null },
    ),
  ).toBe(true);
  expect(sameTokenPricing({ input: "0", output: "1" }, { input: "2", output: "1" })).toBe(false);
});

it("keeps a model pricing currency independent of automatic USD prices", async () => {
  const user = userEvent.setup();
  function CurrencyForm() {
    const [value, setValue] = useState<TokenPricing | null>({ input: "9", output: "0" });
    return (
      <>
        <ModelPricing
          value={value}
          automatic={{ input: "2", output: "3" }}
          currencies={["USD", "EUR"]}
          onChange={setValue}
        />
        <output data-testid="pricing">{JSON.stringify(value)}</output>
      </>
    );
  }
  render(<CurrencyForm />);
  await user.click(screen.getByLabelText("Pricing currency"));
  await user.click(screen.getByRole("option", { name: "EUR" }));
  expect(JSON.parse(screen.getByTestId("pricing").textContent!).currency).toBe("EUR");
  expect(screen.getByLabelText("Input tokens")).toHaveValue(9);
  expect(
    sameTokenPricing(
      { input: "9", output: "0", currency: "USD" },
      { input: "9", output: "0", currency: "EUR" },
    ),
  ).toBe(false);
});
