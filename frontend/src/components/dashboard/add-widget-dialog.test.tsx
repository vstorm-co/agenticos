import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { NextIntlClientProvider } from "next-intl";
import { describe, expect, it, vi } from "vitest";

import messages from "../../../messages/en.json";
import { TooltipProvider } from "@/components/ui";
import { AddWidgetDialog } from "./add-widget-dialog";
import { WIDGETS, type WidgetDef, type WidgetId } from "@/lib/dashboard/registry";
import type { Period } from "@/lib/dashboard/period";

/**
 * The catalog is browsed as often to check what is already on the page as to
 * add something new, and a card may be placed more than once - so "already
 * there" is a thing a row has to say, in words, without going dead.
 */

const PERIOD: Period = { preset: "30d", from: "2026-07-07", to: "2026-08-05" };
const CATALOG: WidgetDef[] = [WIDGETS.platform, WIDGETS.health, WIDGETS.runs];

function renderDialog(placed: Map<WidgetId, number>, onAdd = vi.fn()) {
  // A hovered or clicked row renders that widget for real in the preview pane,
  // so the harness needs the query client and tooltips a live card expects.
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <NextIntlClientProvider locale="en" messages={messages}>
        <TooltipProvider>
          <AddWidgetDialog
            catalog={CATALOG}
            period={PERIOD}
            placed={placed}
            open
            onOpenChange={vi.fn()}
            onAdd={onAdd}
          />
        </TooltipProvider>
      </NextIntlClientProvider>
    </QueryClientProvider>,
  );
  return onAdd;
}

const rowFor = (title: string): HTMLElement =>
  screen.getByRole("button", { name: new RegExp(title) });

describe("the add-a-widget catalog", () => {
  it("marks a card that is already on the page", () => {
    renderDialog(new Map([["health", 1]]));

    expect(
      within(rowFor(messages.dashboard.widgets.health.title)).getByText("On the page"),
    ).toBeInTheDocument();
    expect(
      within(rowFor(messages.dashboard.widgets.runs.title)).queryByText(/On the page/),
    ).toBeNull();
  });

  it("counts the copies, because the answer is sometimes 'twice'", () => {
    renderDialog(new Map([["platform", 3]]));

    expect(
      within(rowFor(messages.dashboard.widgets.platform.title)).getByText("On the page ×3"),
    ).toBeInTheDocument();
  });

  it("still adds a card that is already placed", async () => {
    // Placing the same card twice is allowed - the mark is information, not a
    // gate, so the row must stay live.
    const onAdd = renderDialog(new Map([["health", 2]]));

    await userEvent.click(rowFor(messages.dashboard.widgets.health.title));

    expect(onAdd).toHaveBeenCalledWith("health");
  });
});
