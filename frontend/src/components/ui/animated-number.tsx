"use client";

import { useLocale } from "next-intl";

import { AnimatedCounter } from "@/components/ui/animated-counter";
import { separatorsFor } from "@/lib/number-parts";

/**
 * The two figures worth rolling, both wrapping :func:`AnimatedCounter` with the
 * active locale's own separators.
 *
 * Deliberately not a replacement for the formatters beside them. A counter is
 * for a number somebody *watches* change - the spend headline as the period
 * filter moves, a thread's running cost as the answer arrives - where the roll
 * is what says "this moved". Everywhere a number merely sits on the page (a
 * table cell, a tooltip, a row in a list) `formatUsd` and `toLocaleString` are
 * still right, and cost one span instead of eleven per digit.
 */

interface AnimatedTallyProps {
  /** A count. Rounded and grouped; never money, which has its own component. */
  value: number;
  className?: string;
}

/** A whole number - runs, people, documents - grouped the way the locale groups. */
export function AnimatedTally({ value, className }: AnimatedTallyProps) {
  const { separator } = separatorsFor(useLocale());
  return <AnimatedCounter value={Math.round(value)} separator={separator} className={className} />;
}

interface AnimatedAmountProps {
  /**
   * Dollars. A serialised `Decimal` as often as a number, because that is what
   * the API sends for money - display only, never arithmetic.
   */
  value: string | number | null | undefined;
  /**
   * How many places to draw. Two for a bill; four for what one answer cost,
   * where the whole figure is under a cent and two places is a row of zeroes.
   */
  decimals?: number;
  /**
   * What a screen reader hears.
   *
   * Required rather than optional, and that is the point: the `$` is drawn
   * inside the `aria-hidden` half, so a counter left to read its own digits
   * announces a bare number with no currency on it.
   */
  label: string;
  className?: string;
}

/**
 * Money, rolling to its new value rather than being replaced by it.
 *
 * The separators come from the active locale, so a Polish reader sees
 * `1 234,56` where an English one sees `1,234.56`. The currency symbol does
 * not: the ledger is in dollars whatever language is asking, which is what
 * `formatUsd` already assumes.
 */
export function AnimatedAmount({ value, decimals = 2, label, className }: AnimatedAmountProps) {
  const { separator, decimalSeparator } = separatorsFor(useLocale());

  return (
    <AnimatedCounter
      value={Number(value ?? 0)}
      decimals={decimals}
      separator={separator}
      decimalSeparator={decimalSeparator}
      // i18n-exempt: the currency symbol, not copy - the ledger is in dollars
      // in every locale, and `formatUsd` writes the same character.
      prefix="$"
      label={label}
      className={className}
    />
  );
}
