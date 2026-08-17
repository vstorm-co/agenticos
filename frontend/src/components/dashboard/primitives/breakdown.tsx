"use client";

import type { ReactNode } from "react";

import { seriesColor } from "@/lib/dashboard/system";
import { BarList, type BarListItem } from "./bar-list";
import { DonutChart } from "./donut-chart";

export interface BreakdownRow extends BarListItem {
  icon?: ReactNode;
}

/**
 * One set of named quantities, drawn either way a reader might want it.
 *
 * The two answer different questions about the same rows, which is why the
 * choice is a person's rather than the card's: **bars** rank ("which surface is
 * busiest, and by how much"), and a ring shows **composition** ("what share of
 * everything came from Slack"). Length is the better channel for the first and
 * area for the second, and no card can know which of the two its reader came
 * for.
 *
 * Only the ring spends the categorical ramp - one colour per row, because there
 * position says nothing. The bars stay one hue: that is the rule this
 * dashboard's data ink follows (`system.ts`), and colouring them would
 * re-encode what length already says.
 */
export function Breakdown({
  rows,
  style,
  centerLabel,
  centerSub,
}: {
  rows: BreakdownRow[];
  style: "bars" | "donut";
  /** The number in the ring's middle - the total these rows make up. */
  centerLabel: string;
  centerSub: string;
}) {
  if (style === "donut") {
    const total = rows.reduce((sum, row) => sum + row.value, 0);
    const segments = rows.map((row, index) => ({
      name: row.label,
      value: row.value,
      color: seriesColor(index),
    }));
    return (
      <DonutChart
        className="flex-1"
        segments={segments.filter((segment) => segment.value > 0)}
        legend={segments.map((segment) => ({
          ...segment,
          share: total > 0 ? segment.value / total : 0,
        }))}
        centerLabel={centerLabel}
        centerSub={centerSub}
      />
    );
  }
  return <BarList items={rows} />;
}
