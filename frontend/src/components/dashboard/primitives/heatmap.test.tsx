import { render } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { TooltipProvider } from "@/components/ui";
import { Heatmap } from "./heatmap";

/**
 * Two things about a sequential grid decide whether it answers anything: that
 * one run in a fortnight is still a mark, and that the grid fits the box it was
 * given. The second is why the cells stopped being square - a 24-column grid of
 * squares is 24 units tall whatever height the card has, and in an arranged
 * card it was drawn straight over the title.
 */

const cell = (row: number, column: number, value: number) => ({
  row,
  column,
  value,
  caption: `${row}:${column}`,
});

const marks = (container: HTMLElement): HTMLElement[] =>
  Array.from(container.querySelectorAll<HTMLElement>("div[style*='opacity']"));

describe("the heatmap", () => {
  it("puts the smallest non-zero count on a visible step", () => {
    const { container } = render(
      <TooltipProvider>
        <Heatmap rows={2} columns={2} cells={[cell(0, 0, 1), cell(1, 1, 40)]} />
      </TooltipProvider>,
    );

    const opacities = marks(container).map((mark) => Number(mark.style.opacity));
    expect(opacities).toHaveLength(2);
    expect(Math.min(...opacities)).toBeGreaterThan(0);
    // And the busiest slot is not the same mark as the quietest one, which is
    // the whole reason the ramp is built on the stroke tone rather than on the
    // pastel fill: five steps of a 1.63:1 tint are five shades of nothing.
    expect(Math.max(...opacities)).toBeGreaterThan(Math.min(...opacities));
  });

  it("never runs off the end of the ramp, whatever the peak", () => {
    const { container } = render(
      <TooltipProvider>
        <Heatmap rows={1} columns={2} cells={[cell(0, 0, 5), cell(0, 1, 5)]} />
      </TooltipProvider>,
    );

    for (const mark of marks(container)) {
      expect(Number(mark.style.opacity)).toBeLessThanOrEqual(1);
    }
  });

  it("draws a cell for every slot, including the ones nothing ran in", () => {
    const { container } = render(
      <TooltipProvider>
        <Heatmap rows={3} columns={4} cells={[cell(0, 0, 2)]} />
      </TooltipProvider>,
    );

    expect(container.querySelectorAll("div.rounded-sm")).toHaveLength(12);
  });

  it("sizes its cells from the grid rather than from their own width", () => {
    // `aspect-square` is what made a card overflow its own header: the row
    // template is the height, so the grid fits whatever box it is given.
    const { container } = render(
      <TooltipProvider>
        <Heatmap rows={7} columns={24} cells={[cell(0, 0, 1)]} />
      </TooltipProvider>,
    );
    const grid = container.firstElementChild as HTMLElement;

    expect(grid.style.gridTemplateRows).toBe("repeat(7, minmax(0, 1fr))");
    expect(grid.querySelector(".aspect-square")).toBeNull();
  });
});
