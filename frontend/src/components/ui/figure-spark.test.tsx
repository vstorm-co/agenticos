import type { ReactNode } from "react";
import { render } from "@testing-library/react";
import { NextIntlClientProvider } from "next-intl";
import { expect, it, vi } from "vitest";
import { FigureSpark } from "./figure-spark";

const tooltip = vi.hoisted(() => vi.fn());
vi.mock("recharts", () => ({
  ResponsiveContainer: ({ children }: { children: ReactNode }) => <div>{children}</div>,
  AreaChart: ({ children }: { children: ReactNode }) => <svg>{children}</svg>,
  Area: () => null,
  Tooltip: (props: unknown) => {
    tooltip(props);
    return null;
  },
}));

it("keeps bucket tooltips inside their figure horizontally and above short sparklines", () => {
  render(
    <NextIntlClientProvider locale="en" messages={{}}>
      <FigureSpark spark={[0, 4, 2]} labels={["Mon", "Tue", "Wed"]} color="blue" name="Runs" />
    </NextIntlClientProvider>,
  );
  expect(tooltip).toHaveBeenCalledWith(
    expect.objectContaining({
      allowEscapeViewBox: { x: false, y: true },
      reverseDirection: { y: true },
      isAnimationActive: false,
    }),
  );
});
