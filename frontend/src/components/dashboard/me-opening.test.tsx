import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { MeOpening } from "./me-opening";
import type { Period } from "@/lib/dashboard/period";

/**
 * The person's dashboard opens with Get started and the Briefing side by side
 * (#2301); the Briefing only for whoever may talk to an agent.
 */

const state = vi.hoisted(() => ({ canRun: true }));

vi.mock("@/hooks", () => ({
  usePermissions: () => ({ can: () => state.canRun }),
}));
vi.mock("./start-checklist", () => ({
  StartChecklist: ({ orgId, className }: { orgId: string; className?: string }) => (
    <section aria-label={`checklist:${orgId}`} className={className} />
  ),
}));
vi.mock("./widgets/suggestions", () => ({
  SuggestionsWidget: ({ title, seeAll }: { title: string; seeAll?: string }) => (
    <section aria-label={title} data-see-all={seeAll} />
  ),
}));

const period = { preset: "30d" } as unknown as Period;

beforeEach(() => {
  state.canRun = true;
});

describe("MeOpening", () => {
  it("puts what to do next beside what waits", () => {
    render(<MeOpening orgId="o1" period={period} />);

    expect(screen.getByRole("region", { name: "checklist:o1" })).toHaveClass("mt-0");
    expect(screen.getByRole("region", { name: "Briefing" })).toHaveAttribute(
      "data-see-all",
      "/inbox",
    );
  });

  it("has no checklist without an organization and no briefing without agents:run", () => {
    state.canRun = false;
    render(<MeOpening orgId={null} period={period} />);

    expect(screen.queryByRole("region")).toBeNull();
  });
});
