import { render, screen } from "@testing-library/react";
import { NextIntlClientProvider } from "next-intl";
import { describe, expect, it } from "vitest";

import messages from "../../../../messages/en.json";
import { TooltipProvider } from "@/components/ui";
import { StackedMeter } from "./stacked-meter";

/**
 * What a stacked bar has to hold shut is that every part is *findable*: the
 * numbers are printed, a part that exists is wide enough to see, and a part
 * that does not is still named.
 */

const renderMeter = (segments: { label: string; value: number; color: string }[]) =>
  render(
    <NextIntlClientProvider locale="en" messages={messages}>
      <TooltipProvider>
        <StackedMeter segments={segments} />
      </TooltipProvider>
    </NextIntlClientProvider>,
  );

const widths = (container: HTMLElement): string[] =>
  Array.from(container.querySelectorAll<HTMLElement>("span[style*='width']")).map(
    (span) => span.style.width,
  );

describe("the stacked meter", () => {
  it("keeps a one-in-two-hundred part visible rather than a hairline", () => {
    // Proportional width would be 0.5% - about a pixel in a card, which reads
    // as the border between the parts either side of it rather than as a part.
    const { container } = renderMeter([
      { label: "Owner", value: 1, color: "var(--series-1)" },
      { label: "Member", value: 199, color: "var(--series-2)" },
    ]);

    const [owner] = widths(container);
    expect(Number.parseFloat(owner ?? "0")).toBeGreaterThanOrEqual(2);
  });

  it("draws no band for a part with nothing in it, and still names it", () => {
    const { container } = renderMeter([
      { label: "Owner", value: 2, color: "var(--series-1)" },
      { label: "Viewer", value: 0, color: "var(--series-2)" },
    ]);

    expect(widths(container)).toHaveLength(1);
    expect(screen.getByText("Viewer")).toBeInTheDocument();
    expect(screen.getByText("0%")).toBeInTheDocument();
  });

  it("prints every part's share and count, so colour never carries the value", () => {
    renderMeter([
      { label: "Owner", value: 1, color: "var(--series-1)" },
      { label: "Member", value: 3, color: "var(--series-2)" },
    ]);

    expect(screen.getByText("25%")).toBeInTheDocument();
    expect(screen.getByText("75%")).toBeInTheDocument();
    expect(screen.getByText("3")).toBeInTheDocument();
  });

  it("survives a total of nothing without dividing by it", () => {
    renderMeter([{ label: "Owner", value: 0, color: "var(--series-1)" }]);

    expect(screen.getByText("0%")).toBeInTheDocument();
  });
});
