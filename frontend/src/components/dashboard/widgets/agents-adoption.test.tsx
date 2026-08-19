import { render, screen } from "@testing-library/react";
import { NextIntlClientProvider } from "next-intl";
import { beforeEach, describe, expect, it, vi } from "vitest";

import messages from "../../../../messages/en.json";
import { TooltipProvider } from "@/components/ui";
import { AgentsAdoptionWidget } from "./agents-adoption";
import type { Period } from "@/lib/dashboard/period";

/**
 * Which agents carry the traffic, and whether you can tell them apart.
 *
 * The face is the point of the row: the label column is 144px wide, so
 * "E2E Journey msq2wtqe" truncates and the avatar is what distinguishes two
 * rows whose visible text is identical. It was drawn in a 16px circle with its
 * initials set at 8px, which is a smudge - and two-initial names are exactly
 * the ones the truncation hits.
 */

const useUsageStatsMock = vi.fn();
const useAgentsMock = vi.fn();
vi.mock("@/hooks", () => ({
  useUsageStats: (...args: unknown[]) => useUsageStatsMock(...args),
  useAgents: (...args: unknown[]) => useAgentsMock(...args),
}));

const PERIOD: Period = { preset: "30d", from: "2026-07-19", to: "2026-08-18" };

function renderWidget() {
  useUsageStatsMock.mockReturnValue({
    usage: {
      total_runs: 141,
      by_agent: [
        { agent_id: "a-1", name: "jarvis", runs: 139 },
        { agent_id: "a-2", name: "E2E Journey msq2wtqe", runs: 2 },
      ],
    },
    isLoading: false,
    error: null,
    refetch: vi.fn(),
  });
  useAgentsMock.mockReturnValue({
    agents: [
      { id: "a-1", name: "jarvis", status: "published", has_avatar: false },
      { id: "a-2", name: "E2E Journey msq2wtqe", status: "published", has_avatar: false },
    ],
  });
  return render(
    <NextIntlClientProvider locale="en" messages={messages}>
      <TooltipProvider>
        <AgentsAdoptionWidget title="Agents: adopted and forgotten" hint="" period={PERIOD} />
      </TooltipProvider>
    </NextIntlClientProvider>,
  );
}

beforeEach(() => {
  useUsageStatsMock.mockReset();
  useAgentsMock.mockReset();
});

describe("the agent adoption widget", () => {
  it("draws each agent's face at the size the run table draws it", () => {
    renderWidget();

    // jsdom loads no image, so Radix stays in its fallback state - the initials,
    // which is what a seeded organization actually sees. 20px box, and the
    // avatar's own 10px initials rather than a scale of their own.
    const avatar = screen.getByText("EJ").parentElement;

    expect(avatar).toHaveClass("h-5", "w-5", "text-[10px]");
  });

  it("gives two agents two faces, where their labels both truncate", () => {
    renderWidget();

    expect(screen.getByText("J")).toBeInTheDocument();
    expect(screen.getByText("EJ")).toBeInTheDocument();
  });
});
