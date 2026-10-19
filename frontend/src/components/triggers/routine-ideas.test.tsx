import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { NextIntlClientProvider } from "next-intl";
import { describe, expect, it, vi } from "vitest";

import messages from "../../../messages/en.json";
import { RoutineIdeas } from "./routine-ideas";
import type { TriggerTemplate } from "@/types/trigger-templates";

const catalog = vi.hoisted(() => ({ templates: [] as TriggerTemplate[] }));
vi.mock("@/hooks/use-trigger-templates", () => ({
  useTriggerTemplates: () => ({ templates: catalog.templates, isLoading: false, error: null }),
}));

const BRIEFING: TriggerTemplate = {
  key: "daily-briefing",
  label: "Daily briefing",
  description: "What needs your attention today.",
  prompt: "Brief me.",
  trigger_type: "schedule",
  suggested_cadence: { schedule_kind: "cron", cron_expression: "0 8 * * *" },
};

function renderIdeas(onPick = vi.fn()) {
  render(
    <NextIntlClientProvider locale="en" messages={messages}>
      <RoutineIdeas onPick={onPick} />
    </NextIntlClientProvider>,
  );
  return onPick;
}

describe("RoutineIdeas - ready-made routines to start from", () => {
  it("offers each schedule idea with the cadence it would run on, and picks it", async () => {
    catalog.templates = [
      BRIEFING,
      {
        ...BRIEFING,
        key: "hourly",
        label: "Hourly check",
        suggested_cadence: { schedule_kind: "interval", interval_seconds: 3600 },
      },
      { ...BRIEFING, key: "on-issue", label: "Issue triage", trigger_type: "event" },
    ];
    const onPick = renderIdeas();

    expect(screen.getByText("Daily briefing")).toBeInTheDocument();
    expect(screen.getByText("Daily at 08:00 UTC")).toBeInTheDocument();
    expect(screen.getByText("Every hour")).toBeInTheDocument();
    // An event idea belongs to the event flow's own step, not here.
    expect(screen.queryByText("Issue triage")).toBeNull();

    await userEvent.click(screen.getByRole("button", { name: /Daily briefing/ }));
    expect(onPick).toHaveBeenCalledWith(BRIEFING);
  });

  it("says nothing while there is nothing to offer", () => {
    catalog.templates = [];
    renderIdeas();
    expect(screen.queryByText("Ideas to start from")).toBeNull();
  });
});
