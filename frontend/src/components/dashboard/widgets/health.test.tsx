import { render, screen, within } from "@testing-library/react";
import { NextIntlClientProvider } from "next-intl";
import { beforeEach, describe, expect, it, vi } from "vitest";

import messages from "../../../../messages/en.json";
import { TooltipProvider } from "@/components/ui";
import { HealthWidget } from "./health";
import type { SystemCheck } from "@/types/admin";

/**
 * The card answers one question - is anything down - and it has to answer it
 * for a probe nobody has written a name or an icon for yet. The backend owns
 * that list (`app/services/health.py`); a check it grows is not a check this
 * card may silently drop.
 */

const useSystemHealthMock = vi.fn();
vi.mock("@/hooks", () => ({
  useSystemHealth: () => useSystemHealthMock(),
}));

/** A probe as the endpoint answers one; `detail` is "" unless something failed. */
const check = (key: string, status: SystemCheck["status"], detail = ""): SystemCheck => ({
  key,
  status,
  detail,
  latency_ms: null,
});

function withChecks(checks: SystemCheck[]) {
  useSystemHealthMock.mockReturnValue({
    health: { status: "healthy", checks },
    isLoading: false,
    error: null,
    refetch: vi.fn(),
  });
}

function renderWidget() {
  return render(
    <NextIntlClientProvider locale="en" messages={messages}>
      <TooltipProvider delayDuration={0}>
        <HealthWidget title="Service health" hint="" period={{ preset: "30d", from: "", to: "" }} />
      </TooltipProvider>
    </NextIntlClientProvider>,
  );
}

const tileFor = (name: string): HTMLElement => screen.getByText(name).closest("li") as HTMLElement;

beforeEach(() => useSystemHealthMock.mockReset());

describe("the service health widget", () => {
  it("names the four probes the backend runs, rather than printing their keys", () => {
    withChecks([
      check("database", "healthy"),
      check("redis", "healthy"),
      check("vector_store", "healthy"),
      check("model_access", "healthy"),
    ]);
    renderWidget();

    for (const name of Object.values(messages.dashboard.widgets.health.services)) {
      expect(screen.getByText(name)).toBeInTheDocument();
    }
    expect(screen.queryByText("vector_store")).toBeNull();
  });

  it("shows a probe it has no name or icon for, under its own key", () => {
    withChecks([check("object_storage", "healthy")]);
    renderWidget();

    expect(screen.getByText("object storage")).toBeInTheDocument();
  });

  it("prints the status word beside the tone, never the tone alone", () => {
    withChecks([
      check("database", "healthy"),
      check("redis", "unhealthy", "PING was not answered"),
    ]);
    renderWidget();

    const redis = tileFor(messages.dashboard.widgets.health.services.redis);
    expect(
      within(redis).getByText(messages.dashboard.widgets.health.status.unhealthy),
    ).toBeVisible();
  });

  it("keeps a failing probe's own message, which is the only 'why' on the card", () => {
    // On the hover for a pointer, and in the tile for everyone else: the tile
    // is not a control, so it is not a tab stop, and the sentence would
    // otherwise be reachable only by mouse.
    withChecks([check("redis", "unhealthy", "PING was not answered")]);
    renderWidget();

    const redis = tileFor(messages.dashboard.widgets.health.services.redis);
    expect(within(redis).getByText("PING was not answered")).toBeInTheDocument();
  });
});
