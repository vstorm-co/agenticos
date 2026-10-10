import { fireEvent, render, screen } from "@testing-library/react";
import { NextIntlClientProvider } from "next-intl";
import { beforeEach, describe, expect, it, vi } from "vitest";

import messages from "../../../../messages/en.json";
import { DepartmentSpendWidget } from "./department-spend";
import type { Period } from "@/lib/dashboard/period";
import type { GroupSpend } from "@/types/groups";

const useGroupSpendMock = vi.fn();
vi.mock("@/hooks", () => ({
  useGroupSpend: (...args: unknown[]) => useGroupSpendMock(...args),
}));
vi.mock("@/stores", () => ({
  useOrgStore: (select: (state: { activeOrgId: string }) => unknown) =>
    select({ activeOrgId: "o-1" }),
}));

const PERIOD: Period = { preset: "30d", from: "2026-09-10", to: "2026-10-09" };
const refetch = vi.fn();

function withSpend(state: { items?: GroupSpend[]; isLoading?: boolean; error?: unknown }) {
  useGroupSpendMock.mockReturnValue({
    spend: state.items ? { since: "2026-10-01T00:00:00Z", items: state.items } : undefined,
    isLoading: state.isLoading ?? false,
    error: state.error ?? null,
    refetch,
  });
}

function row(overrides: Partial<GroupSpend>): GroupSpend {
  return {
    group_id: "g-fin",
    name: "Finance",
    icon: "banknote",
    member_count: 4,
    monthly_budget_usd: "50.000000",
    spent_usd: "41.500000",
    run_count: 12,
    ...overrides,
  };
}

function renderWidget() {
  return render(
    <NextIntlClientProvider locale="en" messages={messages}>
      <DepartmentSpendWidget title="Spend by department" hint="" period={PERIOD} />
    </NextIntlClientProvider>,
  );
}

beforeEach(() => useGroupSpendMock.mockReset());

describe("the department spend widget (#2072)", () => {
  it("shows each department against its cap, and an uncapped one as a figure", () => {
    withSpend({
      items: [row({}), row({ group_id: "g-ops", name: "Ops", monthly_budget_usd: null })],
    });
    renderWidget();

    expect(useGroupSpendMock).toHaveBeenCalledWith("o-1");
    expect(screen.getByText("$41.50 / $50.00")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Ops" })).toHaveAttribute("href", "/groups/g-ops");
    expect(screen.getAllByText("$41.50")).toHaveLength(1);
  });

  it("says when there are no departments", () => {
    withSpend({ items: [] });
    renderWidget();

    expect(screen.getByText("No departments yet")).toBeInTheDocument();
  });

  it("loads, and offers a retry when the read fails", () => {
    withSpend({ isLoading: true });
    const { unmount } = renderWidget();
    expect(screen.queryByText("No departments yet")).not.toBeInTheDocument();
    unmount();

    withSpend({ error: new Error("boom") });
    renderWidget();
    fireEvent.click(screen.getByRole("button", { name: /retry/i }));
    expect(refetch).toHaveBeenCalled();
  });
});
