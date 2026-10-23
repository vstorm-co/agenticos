import { render, screen } from "@testing-library/react";
import { NextIntlClientProvider } from "next-intl";
import { beforeEach, describe, expect, it, vi } from "vitest";

import messages from "../../../messages/en.json";
import type { Period } from "@/lib/dashboard/period";
import { firstName, MeHeader, partOfDay } from "./me-header";

const useUsageStatsMock = vi.fn();
vi.mock("@/hooks", () => ({
  useUsageStats: (...args: unknown[]) => useUsageStatsMock(...args),
}));
const others = vi.hoisted(() => ({ value: { review: 0, suites: 0, suggestions: 0 } }));
vi.mock("@/hooks/use-waiting-on-me", () => ({ useWaitingOnMe: () => others.value }));
let user: { full_name?: string | null; email: string } | null = null;
vi.mock("@/stores", () => ({
  useAuthStore: (select: (state: { user: typeof user }) => unknown) => select({ user }),
}));
vi.mock("next/navigation", () => ({ usePathname: () => "/dashboard" }));

const PERIOD: Period = { preset: "30d", from: "2026-09-14", to: "2026-10-13" };

function mount(canRun = true) {
  render(
    <NextIntlClientProvider locale="en" messages={messages}>
      <MeHeader period={PERIOD} canRun={canRun} />
    </NextIntlClientProvider>,
  );
}

beforeEach(() => {
  useUsageStatsMock.mockReset();
  others.value = { review: 0, suites: 0, suggestions: 0 };
  user = { full_name: "Kacper Włodarczyk", email: "kacper@example.com" };
});

describe("partOfDay and firstName", () => {
  it("greets by the hour", () => {
    expect(partOfDay(8)).toBe("morning");
    expect(partOfDay(13)).toBe("afternoon");
    expect(partOfDay(21)).toBe("evening");
  });

  it("calls a person by their first name, else their address", () => {
    expect(firstName("  Kacper  Włodarczyk ", "k@x.io")).toBe("Kacper");
    expect(firstName(null, "kacper@example.com")).toBe("kacper");
    expect(firstName("", undefined)).toBeNull();
  });
});

describe("the Me view's header", () => {
  it("greets the person by name and sums up their period", () => {
    useUsageStatsMock.mockReturnValue({ usage: { total_runs: 73, pending_approvals: 1 } });
    mount();

    expect(screen.getByRole("heading")).toHaveTextContent(
      /Good (morning|afternoon|evening), Kacper/,
    );
    expect(screen.getByText(/73 times/)).toBeVisible();
    expect(screen.getByText("1 call")).toBeVisible();
    expect(useUsageStatsMock).toHaveBeenCalledWith(
      { from: PERIOD.from, to: PERIOD.to },
      { scope: "own", enabled: true },
    );
  });

  it("greets without a name, and describes the page until the usage answers", () => {
    user = null;
    useUsageStatsMock.mockReturnValue({ usage: null });
    mount(false);

    expect(screen.getByRole("heading")).toHaveTextContent(/^.*Good (morning|afternoon|evening)$/);
    expect(screen.getByText(messages.dashboard.views.me.description)).toBeVisible();
    expect(useUsageStatsMock).toHaveBeenCalledWith(expect.anything(), {
      scope: "own",
      enabled: false,
    });
  });

  it("says nothing waits when nothing does", () => {
    useUsageStatsMock.mockReturnValue({ usage: { total_runs: 0, pending_approvals: null } });
    mount();

    expect(screen.getByText(/Nothing is waiting on you/)).toBeVisible();
  });

  it("counts answers to review, failing suites and suggestions as waiting too", () => {
    useUsageStatsMock.mockReturnValue({ usage: { total_runs: 16, pending_approvals: 0 } });
    others.value = { review: 9, suites: 1, suggestions: 1 };
    mount();

    expect(screen.queryByText(/Nothing is waiting on you/)).toBeNull();
    expect(
      screen.getByText("9 answers to review, 1 failing suite, and 1 suggestion"),
    ).toBeVisible();
  });
});
