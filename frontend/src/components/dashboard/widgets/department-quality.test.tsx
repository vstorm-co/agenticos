import { fireEvent, render, screen } from "@testing-library/react";
import { NextIntlClientProvider } from "next-intl";
import { beforeEach, describe, expect, it, vi } from "vitest";

import messages from "../../../../messages/en.json";
import { DepartmentQualityWidget } from "./department-quality";
import type { Period } from "@/lib/dashboard/period";
import type { GroupQuality } from "@/types/groups";

const useGroupsQualityMock = vi.fn();
vi.mock("@/hooks", () => ({
  useGroupsQuality: (...args: unknown[]) => useGroupsQualityMock(...args),
}));
vi.mock("@/stores", () => ({
  useOrgStore: (select: (state: { activeOrgId: string }) => unknown) =>
    select({ activeOrgId: "o-1" }),
}));

const PERIOD: Period = { preset: "30d", from: "2026-09-10", to: "2026-10-09" };
const refetch = vi.fn();

function withQuality(state: { items?: GroupQuality[]; isLoading?: boolean; error?: unknown }) {
  useGroupsQualityMock.mockReturnValue({
    quality: state.items
      ? { from_date: PERIOD.from, to_date: PERIOD.to, items: state.items }
      : undefined,
    isLoading: state.isLoading ?? false,
    error: state.error ?? null,
    refetch,
  });
}

function renderWidget() {
  return render(
    <NextIntlClientProvider locale="en" messages={messages}>
      <DepartmentQualityWidget title="Answer quality by department" hint="" period={PERIOD} />
    </NextIntlClientProvider>,
  );
}

beforeEach(() => useGroupsQualityMock.mockReset());

describe("the department quality widget (#2101)", () => {
  it("reads the dashboard's period and says each department's helpful share", () => {
    withQuality({
      items: [
        { group_id: "g-ops", name: "Ops", icon: null, likes: 1, dislikes: 3 },
        { group_id: "g-fin", name: "Finance", icon: "banknote", likes: 9, dislikes: 1 },
      ],
    });
    renderWidget();

    expect(useGroupsQualityMock).toHaveBeenCalledWith("o-1", {
      from: PERIOD.from,
      to: PERIOD.to,
    });
    expect(screen.getByText("25% helpful · 4 ratings")).toBeInTheDocument();
    expect(screen.getByText("90% helpful · 10 ratings")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Ops" })).toHaveAttribute("href", "/groups/g-ops");
  });

  it("says when no department's people have rated anything", () => {
    withQuality({ items: [] });
    renderWidget();

    expect(screen.getByText("No department ratings yet")).toBeInTheDocument();
  });

  it("loads, and offers a retry when the read fails", () => {
    withQuality({ isLoading: true });
    const { unmount } = renderWidget();
    expect(screen.queryByText("No department ratings yet")).not.toBeInTheDocument();
    unmount();

    withQuality({ error: new Error("boom") });
    renderWidget();
    fireEvent.click(screen.getByRole("button", { name: /retry/i }));
    expect(refetch).toHaveBeenCalled();
  });
});
