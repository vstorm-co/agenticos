import Decimal from "decimal.js";
import type { CurrencyContext } from "@/lib/currency-api";

// Keep financial arithmetic independent of graph/widget Decimal configuration.
const Money = Decimal.clone({ precision: 128, rounding: Decimal.ROUND_HALF_EVEN });
type Amount = string | number | null | undefined;
export interface CurrencyAmount {
  amount: string;
  currency: string;
}
export interface MonetaryTerm extends CurrencyAmount {
  units_per_usd: string;
  cost_usd: string;
}
export interface MonetaryWrite {
  usd: string;
  input: CurrencyAmount;
}
interface MoneyDisplay {
  currency: string | null;
  available: boolean;
  quote: string | null;
  amount(value: Amount): number | null;
  inputValue(value: Amount, locale?: string): string;
  plan(value: string, locale?: string): MonetaryWrite | null;
  format(value: Amount, locale: string, digits?: number): string;
  cost(value: Amount, locale: string): string;
  formatAmount(value: number | null, locale: string, digits?: number): string;
}

function decimal(value: Amount): Decimal | null {
  const raw = String(value ?? 0).trim();
  if (!raw || raw.length > 128) return null;
  try {
    const parsed = new Money(raw);
    // Bound exponent before toFixed: arbitrary user exponents must not allocate
    // millions of digits. Owner schemas apply their narrower domain limits.
    return parsed.isFinite() && Math.abs(parsed.e) <= 80 ? parsed : null;
  } catch {
    return null;
  }
}

function localized(value: Decimal, currency: string, locale: string, digits: number): string {
  const fixed = value.toFixed(digits);
  const [integer = "0", fraction = ""] = fixed.split(".");
  const whole = BigInt(integer);
  const number = new Intl.NumberFormat(locale, {
    ...(currency === "USD" ? {} : { style: "currency", currency, currencyDisplay: "code" }),
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  });
  const parts = number.formatToParts(whole === BigInt(0) && value.isNegative() ? -0 : whole);
  const renderedFraction = new Intl.NumberFormat(locale, {
    useGrouping: false,
    minimumIntegerDigits: Math.max(1, digits),
  }).format(BigInt(fraction || "0"));
  const rendered = parts
    .map((part) => (part.type === "fraction" ? renderedFraction : part.value))
    .join("");
  return currency === "USD" ? `$${rendered}` : rendered;
}

/** The persisted reporting quote is shared by displays and limit entry.
 * Current pricing rates intentionally do not revalue historical reporting.
 */
export function moneyFor(context: CurrencyContext | null): MoneyDisplay {
  const currency = context?.currency ?? null;
  const parsedRate =
    context?.reporting_units_per_usd == null ? null : decimal(context.reporting_units_per_usd);
  const rate = parsedRate?.gt(0) ? parsedRate : null;
  const available = currency !== null && rate !== null;
  const converted = (value: Amount): Decimal | null => {
    const usd = decimal(value);
    return rate !== null && usd !== null ? usd.mul(rate) : null;
  };
  const amount = (value: Amount): number | null => {
    const result = converted(value)?.toNumber();
    return result !== undefined && Number.isFinite(result) ? result : null;
  };
  const inputValue = (value: Amount, locale?: string): string => {
    const text = value == null ? "" : (converted(value)?.toFixed() ?? "");
    const separator = locale
      ? new Intl.NumberFormat(locale).formatToParts(1.1).find((part) => part.type === "decimal")
          ?.value
      : ".";
    return separator && separator !== "." ? text.replace(".", separator) : text;
  };
  const plan = (value: string, locale?: string): MonetaryWrite | null => {
    const separator = locale
      ? new Intl.NumberFormat(locale).formatToParts(1.1).find((part) => part.type === "decimal")
          ?.value
      : ".";
    const normalized = separator && separator !== "." ? value.replaceAll(separator, ".") : value;
    const original = decimal(normalized);
    if (
      !available ||
      currency === null ||
      rate === null ||
      original === null ||
      original.isNegative()
    )
      return null;
    const usd = currency === "USD" ? original : original.div(rate).toDecimalPlaces(6);
    if (original.gt(0) && usd.isZero()) return null;
    return { usd: usd.toFixed(), input: { amount: original.toFixed(), currency } };
  };
  const formatAmount = (value: number | null, locale: string, digits = 2): string => {
    const parsed = value === null ? null : decimal(value);
    return parsed === null || currency === null || !available
      ? "—"
      : localized(parsed, currency, locale, digits);
  };
  const format = (value: Amount, locale: string, digits = 2): string => {
    const result = converted(value);
    return result === null || currency === null ? "—" : localized(result, currency, locale, digits);
  };
  const cost = (value: Amount, locale: string): string => {
    const result = value == null ? null : converted(value);
    if (result === null || currency === null) return "—";
    const absolute = result.abs();
    if (!absolute.isZero() && absolute.lt("0.000000000001")) {
      return `< ${localized(new Money("0.000000000001"), currency, locale, 12)}`;
    }
    const digits =
      !absolute.isZero() && absolute.lt("0.01")
        ? Math.min(12, Math.max(4, 1 - absolute.e))
        : Math.min(4, Math.max(2, result.toDecimalPlaces(4).decimalPlaces()));
    return localized(result, currency, locale, digits);
  };
  return {
    currency,
    available,
    quote: rate?.toFixed() ?? null,
    amount,
    inputValue,
    plan,
    format,
    formatAmount,
    cost,
  };
}

/** Compare canonical USD without a binary-float round trip. */
export function compareUsd(left: string, right: string | number): number | null {
  const a = decimal(left),
    b = decimal(right);
  return a === null || b === null ? null : a.comparedTo(b);
}

/** Normalize a validated API amount for a draft without converting its unit. */
export function canonicalUsd(value: Amount): string {
  if (value == null || value === "") return "";
  const parsed = decimal(value);
  // i18n-exempt: an invalid typed API amount is a contract failure, not form copy.
  if (parsed === null) throw new TypeError("Invalid accounting USD amount");
  return parsed.toFixed();
}
