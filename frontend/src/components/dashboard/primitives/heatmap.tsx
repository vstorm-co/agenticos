"use client";

import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui";
import { QUIET_SURFACE, STROKE_TOKEN } from "@/lib/dashboard/system";
import { cn } from "@/lib/utils";

export interface HeatCell {
  row: number;
  column: number;
  value: number;
  /** What the hover says about this cell, already translated. */
  caption: string;
}

/**
 * The five steps, as opacity over one tone.
 *
 * A sequential ramp needs *range*: the pastel fill every bar is drawn in
 * measures 1.63:1 against the card, so five steps of it are five shades of
 * nearly-white and the busiest hour of the week reads the same as a quiet one.
 * The ramp is built on the stroke tone instead - the same hue, the fuller
 * step - so the top of the scale is a mark and the bottom is a tint.
 */
const STEPS = [0.18, 0.36, 0.56, 0.78, 1] as const;

/**
 * A grid where colour is magnitude - one hue, light to dark.
 *
 * Sequential, not categorical: the cells are ordered by how much, so they take
 * one hue in steps rather than five hues in a fixed order. Five steps, because
 * past about seven bins adjacent classes blur and the grid stops answering
 * "when is it busy" and starts answering nothing. Zero is not a step: a slot
 * nothing ran in takes the quiet surface, so "never" and "barely" are different
 * marks rather than two shades of the same one.
 *
 * **The cells fill the box they are given rather than being square.** They were
 * `aspect-square`, which makes a 24-column grid 24 units tall whatever height
 * the card has - so in a card whose height its owner had chosen, a hundred and
 * sixty-eight cells were drawn straight over the title. A cell is a rectangle
 * now; the grid fits, and the caller gives it a floor to stop it collapsing.
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
      className={cn("grid min-h-0 gap-[3px]", className)}
      style={{
        // i18n-exempt: a CSS grid template, not words on screen
        gridTemplateColumns: `repeat(${columns}, minmax(0, 1fr))`,
        // i18n-exempt: a CSS grid template, not words on screen
        gridTemplateRows: `repeat(${rows}, minmax(0, 1fr))`,
      }}
    >
      {Array.from({ length: rows * columns }, (_, index) => {
        const row = Math.floor(index / columns);
        const column = index % columns;
        const cell = byKey.get(`${row}:${column}`);
        if (!cell || cell.value === 0) {
          // Half strength: a hundred and forty empty slots at the full quiet
          // surface are a wall of grey with the data lost in it, and on this
          // grid "nothing ran" is the background rather than a reading.
          return (
            <div
              key={index}
              className={cn("h-full w-full rounded-sm opacity-50", QUIET_SURFACE)}
              aria-hidden
            />
          );
        }
        // `Math.ceil` puts any non-zero count on at least the first step, so one
        // run in a week is visible rather than rounded away into the empty cells
        // around it.
        const step = Math.min(STEPS.length, Math.ceil((cell.value / peak) * STEPS.length));
        return (
          <Tooltip key={index}>
            <TooltipTrigger asChild>
              <div
                className="h-full w-full rounded-sm"
                style={{ background: STROKE_TOKEN, opacity: STEPS[step - 1] }}
              />
            </TooltipTrigger>
            <TooltipContent side="top">{cell.caption}</TooltipContent>
          </Tooltip>
        );
      })}
    </div>
  );
}
