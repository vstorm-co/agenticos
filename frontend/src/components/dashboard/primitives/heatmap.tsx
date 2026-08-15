"use client";

import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui";
import { QUIET_SURFACE } from "@/lib/dashboard/system";
import { cn } from "@/lib/utils";

export interface HeatCell {
  row: number;
  column: number;
  value: number;
  /** What the hover says about this cell, already translated. */
  caption: string;
}

/**
 * A grid where colour is magnitude - one hue, light to dark.
 *
 * Sequential, not categorical: the cells are ordered by how much, so they take
 * one hue in steps rather than eight hues in a fixed order. The steps are
 * opacity over `--color-chart`, which keeps the ramp in the accent's own hue in
 * both themes without a second palette to validate.
 *
 * Five steps, because past about seven bins adjacent classes blur and the grid
 * stops answering "when is it busy" and starts answering nothing. Zero is not a
 * step: a slot nothing ran in takes the quiet surface, so "never" and "barely"
 * are different marks rather than two shades of the same one.
 *
 * Colour is never the only channel: every cell carries a hover naming its slot
 * and its count, and the caller draws the axis labels around it.
 */
export function Heatmap({
  cells,
  rows,
  columns,
  className,
}: {
  cells: HeatCell[];
  rows: number;
  columns: number;
  className?: string;
}) {
  const byKey = new Map(cells.map((cell) => [`${cell.row}:${cell.column}`, cell]));
  const peak = Math.max(...cells.map((cell) => cell.value), 1);

  return (
    <div
      className={cn("grid gap-0.5", className)}
      // i18n-exempt: a CSS grid template, not words on screen
      style={{ gridTemplateColumns: `repeat(${columns}, minmax(0, 1fr))` }}
    >
      {Array.from({ length: rows * columns }, (_, index) => {
        const row = Math.floor(index / columns);
        const column = index % columns;
        const cell = byKey.get(`${row}:${column}`);
        if (!cell || cell.value === 0) {
          return (
            <div
              key={index}
              className={cn("aspect-square rounded-[2px]", QUIET_SURFACE)}
              aria-hidden
            />
          );
        }
        // Five steps over the accent. `Math.ceil` puts any non-zero count on at
        // least the first step, so one run in a week is visible rather than
        // rounded away into the empty cells around it.
        const step = Math.ceil((cell.value / peak) * 5);
        return (
          <Tooltip key={index}>
            <TooltipTrigger asChild>
              <div
                className="bg-chart aspect-square rounded-[2px]"
                style={{ opacity: 0.2 * step }}
              />
            </TooltipTrigger>
            <TooltipContent side="top">{cell.caption}</TooltipContent>
          </Tooltip>
        );
      })}
    </div>
  );
}
