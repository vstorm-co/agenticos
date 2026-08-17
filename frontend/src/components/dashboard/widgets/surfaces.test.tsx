import { render, screen } from "@testing-library/react";
import { NextIntlClientProvider } from "next-intl";
import { beforeEach, describe, expect, it, vi } from "vitest";

import messages from "../../../../messages/en.json";
import { TooltipProvider } from "@/components/ui";
import { SurfacesWidget } from "./surfaces";
import type { Period } from "@/lib/dashboard/period";

/**
 * A card that says "Mattermost 31" and cannot offer those 31 is a dead end.
 * Every row here reaches Activity narrowed to its own surface, over the window
 * the row was counted in (#768).
 */

const useUsageStatsMock = vi.fn();
vi.mock("@/hooks", () => ({
  useUsageStats: (...args: unknown[]) => useUsageStatsMock(...args),
}));

const PERIOD: Period = { preset: "90d", from: "2026-05-18", to: "2026-08-15" };

function renderWidget() {
  useUsageStatsMock.mockReturnValue({
    usage: {
      total_runs: 47,
      by_surface: [
        { surface: "mattermost", runs: 31 },
        { surface: "web", runs: 16 },
      ],
    },
    isLoading: false,
    error: null,
    refetch: vi.fn(),
  });
  return render(
    <NextIntlClientProvider locale="en" messages={messages}>
      <TooltipProvider>
        <SurfacesWidget title="Where runs come from" hint="" period={PERIOD} />
      </TooltipProvider>
    </NextIntlClientProvider>,
  );
}

beforeEach(() => useUsageStatsMock.mockReset());

describe("the surfaces widget", () => {
  it("points each row at the runs behind it, over the same window", () => {
    renderWidget();

    const row = screen.getByRole("link", {
      name: messages.dashboard.widgets.surfaces.names.mattermost,
    });
    const href = decodeURIComponent(row.getAttribute("href") ?? "");

    expect(href).toContain("/runs?");
    expect(href).toContain("surface=mattermost");
    expect(href).toContain("period=90d");
  });

  it("draws the surface's own mark beside its name", () => {
    const { container } = renderWidget();

    // The marks the run table draws, from the same module - decorative, so the
    // name beside them is what carries the row.
    expect(container.querySelectorAll("svg[aria-hidden]").length).toBeGreaterThanOrEqual(2);
  });
});
