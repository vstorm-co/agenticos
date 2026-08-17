import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { NextIntlClientProvider } from "next-intl";
import { describe, expect, it, vi } from "vitest";

import messages from "../../../messages/en.json";
import { PeriodControl } from "./period-control";
import { resolvePreset, type Period } from "@/lib/dashboard/period";

/**
 * The shared window strip - the one control the dashboard and the Activity
 * page both ask about time through. What matters: a preset click answers with
 * that preset resolved, the calendar answers with a custom range, and the
 * active choice is marked so a reader can see which window the page is on.
 */

function renderControl(period: Period, onChange = vi.fn()) {
  render(
    <NextIntlClientProvider locale="en" messages={messages}>
      <PeriodControl period={period} onChange={onChange} />
    </NextIntlClientProvider>,
  );
  return onChange;
}

describe("PeriodControl", () => {
  it("marks the active preset and answers a click with the preset resolved", async () => {
    const onChange = renderControl(resolvePreset("30d"));

    expect(screen.getByRole("button", { name: "Last 30 days" })).toHaveAttribute(
      "aria-pressed",
      "true",
    );

    await userEvent.click(screen.getByRole("button", { name: "Last 7 days" }));

    expect(onChange).toHaveBeenCalledTimes(1);
    expect(onChange.mock.calls[0]?.[0]).toMatchObject({ preset: "7d" });
  });

  it("answers two calendar picks with the range, in either click order", async () => {
    // Dates relative to the real clock, because the picker opens on the two
    // months around today - a hard-coded date would leave the visible grid as
    // the calendar moves on.
    const today = new Date();
    const earlier = new Date(today);
    earlier.setUTCDate(earlier.getUTCDate() - 5);
    const [to, from] = [today, earlier].map((date) => date.toISOString().slice(0, 10));

    const onChange = renderControl(resolvePreset("30d"));

    await userEvent.click(screen.getByRole("button", { name: "Custom range" }));
    // Later date first: the picker orders the pair itself.
    await userEvent.click(await screen.findByRole("button", { name: to }));
    await userEvent.click(screen.getByRole("button", { name: from }));

    expect(onChange).toHaveBeenCalledWith({ preset: "custom", from, to });
  });

  it("names the custom range on its own trigger once one is active", () => {
    renderControl({ preset: "custom", from: "2026-08-03", to: "2026-08-10" });

    const trigger = screen.getByRole("button", { name: /2026-08-03 – 2026-08-10/ });
    expect(trigger).toHaveAttribute("aria-pressed", "true");
  });
});
