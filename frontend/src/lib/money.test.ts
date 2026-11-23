import { describe, expect, it } from "vitest";
import { moneyFor } from "./money";
import type { CurrencyContext } from "./currency-api";

const context: CurrencyContext = {
  currency: "PLN",
  default_currency: "PLN",
  inherited: true,
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
    const money = moneyFor({ ...context, currency: "USD" });
    expect(money.format("2", "en")).toBe("$2.00");
    expect(money.format("0.0003", "en", 4)).toBe("$0.0003");
    expect(money.formatAmount(0.01, "en")).toBe("$0.01");
  });

  it.each(["0", "-1", "NaN", "Infinity", ""])('refuses an unusable rate "%s"', (rate) => {
    const money = moneyFor({ ...context, rates: { USD: "1", PLN: rate } });
    expect(money.available).toBe(false);
    expect(money.amount("1")).toBeNull();
    expect(money.format("1", "en")).toBe("—");
  });

  it("keeps missing context, missing rates and invalid amounts visibly unknown", () => {
    expect(moneyFor(null).format("1", "en")).toBe("—");
    expect(moneyFor({ ...context, rates: { USD: "1" } }).format("1", "en")).toBe("—");
    expect(moneyFor(context).format("NaN", "en")).toBe("—");
    expect(moneyFor(context).format("Infinity", "en")).toBe("—");
    expect(moneyFor(context).formatAmount(null, "en")).toBe("—");
    expect(moneyFor(context).formatAmount(Infinity, "en")).toBe("—");
  });
});
