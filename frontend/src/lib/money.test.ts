import { describe, expect, it } from "vitest";
import { moneyFor } from "./money";
import type { CurrencyContext } from "./currency-api";

const context: CurrencyContext = {
  currency: "PLN",
  default_currency: "PLN",
  inherited: true,
  reporting_units_per_usd: "4",
  rates: { USD: "1", PLN: "4", EUR: "0.9", NOK: "10.5" },
};

describe("organization money display", () => {
  it("uses the same conversion for spend and caps, independently of language", () => {
    const money = moneyFor(context);
    expect(money.amount("14")).toBe(56);
    expect(money.amount("100")).toBe(400);
    expect(money.format("14", "en")).toContain("PLN");
    expect(money.format("14", "pl")).toContain("PLN");
    expect(money.format("14", "en")).toContain("56.00");
    expect(money.format("14", "pl")).toContain("56,00");
    expect(context.rates.PLN).toBe("4");
  });

  it.each([undefined, null, "0", 0])("preserves a measured zero %s", (value) => {
    expect(moneyFor(context).amount(value)).toBe(0);
  });

  it("preserves the established dollar display and precision", () => {
    const money = moneyFor({ ...context, currency: "USD", reporting_units_per_usd: "1" });
    expect(money.format("2", "en")).toBe("$2.00");
    expect(money.format("0.0003", "en", 4)).toBe("$0.0003");
    expect(money.formatAmount(0.01, "en")).toBe("$0.01");
  });

  it.each(["0", "-1", "NaN", "Infinity", ""])('refuses an unusable rate "%s"', (rate) => {
    const money = moneyFor({ ...context, reporting_units_per_usd: rate });
    expect(money.available).toBe(false);
    expect(money.amount("1")).toBeNull();
    expect(money.format("1", "en")).toBe("—");
  });

  it("keeps missing context, missing rates and invalid amounts visibly unknown", () => {
    expect(moneyFor(null).format("1", "en")).toBe("—");
    expect(moneyFor({ ...context, reporting_units_per_usd: null }).format("1", "en")).toBe("—");
    expect(moneyFor(context).format("NaN", "en")).toBe("—");
    expect(moneyFor(context).format("Infinity", "en")).toBe("—");
    expect(moneyFor(context).formatAmount(null, "en")).toBe("—");
    expect(moneyFor(context).formatAmount(Infinity, "en")).toBe("—");
  });
});

describe("exact monetary declarations", () => {
  it("freezes reporting while current pricing FX changes", () => {
    expect(moneyFor({ ...context, rates: { USD: "1", PLN: "9" } }).format("25", "en")).toContain(
      "100.00",
    );
  });
  it("does not round a large amount through a binary float", () => {
    const usd = moneyFor({ ...context, currency: "USD", reporting_units_per_usd: "1" });
    expect(usd.format("9007199254740993.05", "en")).toBe("$9,007,199,254,740,993.05");
    expect(usd.plan("9007199254740993.05")?.usd).toBe("9007199254740993.05");
  });
  it("uses the same quote for input and display without reinterpreting USD", () => {
    const money = moneyFor(context);
    expect(money.inputValue("25.000000")).toBe("100");
    expect(money.plan("100")).toEqual({ usd: "25", input: { amount: "100", currency: "PLN" } });
    expect(money.inputValue(null)).toBe("");
    expect(moneyFor(null).plan("100")).toBeNull();
  });
  it.each(["", " ", "not money", "Infinity", "-1", "1e999999", "1e-999999", "0.00000001"])(
    "refuses unusable input %s",
    (input) => {
      expect(moneyFor(context).plan(input)).toBeNull();
    },
  );
  it("rounds accounting amounts half-even and localizes exact fractions", () => {
    const money = moneyFor(context);
    expect(money.plan("0.000006")?.usd).toBe("0.000002");
    expect(money.plan("0.00001")?.usd).toBe("0.000002");
    expect(money.format("-0.01", "pl")).toContain("-0,04");
  });
});

it("accepts locale decimal separators without treating grouping as a decimal", () => {
  const money = moneyFor(context);
  expect(money.inputValue("25.125", "pl")).toBe("100,5");
  expect(money.plan("100,5", "pl")).toEqual({
    usd: "25.125",
    input: { amount: "100.5", currency: "PLN" },
  });
  expect(money.plan("1.234,56", "pl")).toBeNull();
  expect(money.plan("100,5", "en")).toBeNull();
});
it("does not present small known costs as free or missing usage as zero", () => {
  const money = moneyFor(context);
  expect(money.cost("0.00000005", "en")).toContain("0.00000020");
  expect(money.cost("0.00000000000001", "en")).toContain("<");
  expect(money.cost(null, "en")).toBe("—");
  expect(money.cost("0", "en")).toContain("0.00");
});
