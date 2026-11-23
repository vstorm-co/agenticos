import type { CurrencyContext } from "@/lib/currency-api";

interface MoneyDisplay {
  currency: string | null;
  available: boolean;
  amount(value: string | number | null | undefined): number | null;
  format(value: string | number | null | undefined, locale: string, digits?: number): string;
  formatAmount(value: number | null, locale: string, digits?: number): string;
}

/** A display conversion of canonical USD amounts; never rewrites recorded money. */
export function moneyFor(context: CurrencyContext | null): MoneyDisplay {
  const currency = context?.currency ?? null;
  const rate = currency === null ? NaN : Number(context?.rates[currency]);
  const available = currency !== null && Number.isFinite(rate) && rate > 0;
  const amount = (value: string | number | null | undefined): number | null => {
    const usd = Number(value ?? 0);
    const converted = usd * rate;
    return available && Number.isFinite(converted) ? converted : null;
  };
  const formatAmount = (converted: number | null, locale: string, digits = 2): string => {
    if (converted === null || !Number.isFinite(converted) || currency === null) return "—";
    // Preserve existing dollar displays; other currencies use their explicit
    // code so a language preference cannot make two currencies ambiguous.
    if (currency === "USD") {
      return `$${converted.toLocaleString(locale, { minimumFractionDigits: digits, maximumFractionDigits: digits })}`;
    }
    return new Intl.NumberFormat(locale, {
      style: "currency",
      currency,
      currencyDisplay: "code",
      minimumFractionDigits: digits,
      maximumFractionDigits: digits,
    }).format(converted);
  };
  const format = (value: string | number | null | undefined, locale: string, digits = 2) =>
    formatAmount(amount(value), locale, digits);
  return { currency, available, amount, format, formatAmount };
}
