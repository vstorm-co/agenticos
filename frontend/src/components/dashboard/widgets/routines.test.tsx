import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { NextIntlClientProvider } from "next-intl";
import { beforeEach, describe, expect, it, vi } from "vitest";

import messages from "../../../../messages/en.json";
import { TooltipProvider } from "@/components/ui";
import { RoutinesWidget } from "./routines";
import type { Period } from "@/lib/dashboard/period";
import type { AgentRun } from "@/types/runs";
import type { Trigger } from "@/types/triggers";

/**
 * What runs with nobody at the keyboard, and how the last one went.
 *
 * The card's whole reason for existing is the *outcome*: a routine failing every
 * hour for a day looks identical to a healthy one on a card that only says when
 * it next fires. So most of what is asserted here is the pill.
 */

const useOrgTriggersMock = vi.fn();
const useRunsMock = vi.fn();
const canMock = vi.fn();

vi.mock("@/hooks/use-org-triggers", () => ({
  useOrgTriggers: () => useOrgTriggersMock(),
}));
vi.mock("@/hooks", () => ({
  useRuns: (...args: unknown[]) => useRunsMock(...args),
  usePermissions: () => ({ can: canMock }),
}));

const PERIOD: Period = { preset: "30d", from: "2026-07-19", to: "2026-08-18" };

function trigger(overrides: Partial<Trigger> = {}): Trigger {
  return {
    id: "t-1",
    agent_id: "a-1",
    agent_name: "jarvis",
    name: "Morning digest",
    created_by_user_id: null,
    is_active: true,
    can_manage: true,
    environment_id: null,
    trigger_type: "schedule",
    schedule_kind: "interval",
    interval_seconds: 900,
    cron_expression: null,
    event_source: null,
    event_config: {},
    prompt: "summarise",
    next_fire_at: "2026-08-21T09:00:00Z",
    last_fired_at: "2026-08-21T08:45:00Z",
    last_run_id: "r-1",
    conversation_id: null,
    webhook_url: null,
    created_at: null,
    updated_at: null,
    ...overrides,
  };
}

function run(overrides: Partial<AgentRun> = {}): AgentRun {
  return {
    id: "r-1",
    agent_id: "a-1",
    agent_version_id: null,
    user_id: null,
    surface: "schedule",
    status: "completed",
    model_label: null,
    provider: null,
    input_tokens: 0,
    output_tokens: 0,
    cost_usd: "0.0042",
    cost_is_partial: false,
    logfire_trace_id: null,
    error: null,
    down_rated: false,
    ...overrides,
  } as AgentRun;
}

function renderWidget(triggers: Trigger[], runs: AgentRun[] = [run()]) {
  useOrgTriggersMock.mockReturnValue({
    triggers,
    isLoading: false,
    isError: false,
    refetch: vi.fn(),
  });
  useRunsMock.mockReturnValue({ runs, total: runs.length, isLoading: false, error: null });
  render(
    <NextIntlClientProvider locale="en" messages={messages}>
      <TooltipProvider>
        <RoutinesWidget title="Routines" hint="" period={PERIOD} />
      </TooltipProvider>
    </NextIntlClientProvider>,
  );
}

beforeEach(() => {
  useOrgTriggersMock.mockReset();
  useRunsMock.mockReset();
  canMock.mockReset();
  canMock.mockReturnValue(true);
});

describe("the routines widget", () => {
  it("says how the last fire went, not only when the next one is", () => {
    renderWidget([trigger()]);

    expect(screen.getByText("Morning digest")).toBeVisible();
    expect(screen.getByText("ok")).toBeVisible();
  });

  it("marks a failed routine, which is the row somebody opened this card for", () => {
    renderWidget([trigger()], [run({ status: "failed" })]);

    expect(screen.getByText("failed")).toBeVisible();
  });

  it("marks a routine whose run was over budget", () => {
    renderWidget([trigger()], [run({ status: "budget_exceeded" })]);

    expect(screen.getByText("over budget")).toBeVisible();
  });

  it("marks a run somebody rated down, which succeeded and was still wrong", () => {
    renderWidget([trigger()], [run({ down_rated: true })]);

    expect(screen.getByText("rated down")).toBeVisible();
  });

  it("says a routine is paused rather than reporting its last outcome", () => {
    // A paused routine's last run may well have succeeded; saying "ok" would
    // read as "this is working", which is the opposite of the truth.
    renderWidget([trigger({ is_active: false })]);

    expect(screen.getByText("paused")).toBeVisible();
  });

  it("distinguishes a routine that has never fired", () => {
    renderWidget([trigger({ last_fired_at: null, last_run_id: null })]);

    expect(screen.getByText("not run yet")).toBeVisible();
  });

  it("says only that it fired when the run is out of reach", () => {
    // Older than the page of recent runs, or a reader who may not read runs at
    // all. "Succeeded" would be a guess and "failed" a worse one.
    renderWidget([trigger()], []);

    expect(screen.getByText("fired")).toBeVisible();
  });

  it("reports a run still in flight as itself", () => {
    renderWidget([trigger()], [run({ status: "running" })]);

    expect(screen.getByText("running")).toBeVisible();
  });

  it("shows the cadence and what the last run cost", () => {
    renderWidget([trigger()]);

    expect(screen.getByText(/Every 15 minutes/)).toBeVisible();
    expect(screen.getByText(/\$0\.0042/)).toBeVisible();
  });

  it("says when a live schedule fires next", () => {
    // Matched on the caption word, not the formatted instant: the time renders in
    // the machine's own timezone, which differs between a laptop and CI.
    renderWidget([trigger({ next_fire_at: "2099-01-05T12:00:00Z" })]);

    expect(screen.getByText(/next /)).toBeVisible();
  });

  it("does not call an overdue fire 'next' - a missed time is not a future", () => {
    // The heartbeat claims a due schedule at tick time, so a next_fire_at in the
    // past is a fire that has not happened yet; "next <past instant>" would
    // assert a future that already failed, loudest exactly when the worker is
    // down. The fixture's default next_fire_at is such an instant.
    renderWidget([trigger()]);

    expect(screen.queryByText(/next /)).toBeNull();
  });

  it("gives a paused routine no next fire, whatever its row still holds", () => {
    renderWidget([trigger({ is_active: false, next_fire_at: "2099-01-05T12:00:00Z" })]);

    expect(screen.queryByText(/next /)).toBeNull();
    expect(screen.getByText("paused")).toBeVisible();
  });

  it("reads an event trigger's own phrase rather than a cadence it has none of", () => {
    renderWidget([
      trigger({
        trigger_type: "event",
        event_source: "github",
        next_fire_at: null,
        interval_seconds: null,
      }),
    ]);

    expect(screen.getByText(/GitHub/)).toBeVisible();
  });

  it("does not ask for runs when the reader may not read them", () => {
    // The triggers half needs `agents:view` and the outcome half `runs:view`, so
    // a reader with the first and not the second gets the routines rather than a
    // card that 403s on a permission it never needed.
    canMock.mockReturnValue(false);
    renderWidget([trigger()]);

    expect(useRunsMock).toHaveBeenCalledWith(undefined, {
      surface: "schedule",
      enabled: false,
    });
  });

  it("puts what is about to happen first, and the paused last", () => {
    renderWidget([
      trigger({ id: "t-paused", name: "Paused one", is_active: false }),
      trigger({ id: "t-soon", name: "Soon", next_fire_at: "2026-08-21T08:00:00Z" }),
      trigger({ id: "t-later", name: "Later", next_fire_at: "2026-08-21T20:00:00Z" }),
      trigger({ id: "t-event", name: "On an issue", trigger_type: "event", next_fire_at: null }),
    ]);

    const labels = screen.getAllByRole("listitem").map((row) => row.textContent);

    expect(labels[0]).toContain("Soon");
    expect(labels[1]).toContain("Later");
    // Live but not on a clock: after the schedules, before the paused.
    expect(labels[2]).toContain("On an issue");
    expect(labels[3]).toContain("Paused one");
  });

  it("lists a routine by its agent when it has no name of its own", () => {
    renderWidget([trigger({ name: null })]);

    expect(screen.getByText("jarvis")).toBeVisible();
  });

  it("falls back to a word rather than an empty row when neither is known", () => {
    renderWidget([trigger({ name: null, agent_name: null })]);

    expect(screen.getByText("Untitled routine")).toBeVisible();
  });

  it("stops at six rows and leaves the rest to the page", () => {
    renderWidget(
      Array.from({ length: 9 }, (_, index) =>
        trigger({ id: `t-${index}`, name: `Routine ${index}` }),
      ),
    );

    expect(screen.getAllByRole("listitem")).toHaveLength(6);
  });

  it("says nothing runs on its own yet, rather than drawing an empty list", () => {
    renderWidget([]);

    expect(screen.getByText("Nothing runs on its own yet")).toBeVisible();
  });

  it("draws a placeholder while the list is being read", () => {
    useOrgTriggersMock.mockReturnValue({
      triggers: [],
      isLoading: true,
      isError: false,
      refetch: vi.fn(),
    });
    useRunsMock.mockReturnValue({ runs: [], total: 0, isLoading: true, error: null });
    render(
      <NextIntlClientProvider locale="en" messages={messages}>
        <TooltipProvider>
          <RoutinesWidget title="Routines" hint="" period={PERIOD} />
        </TooltipProvider>
      </NextIntlClientProvider>,
    );

    expect(screen.queryByText("Nothing runs on its own yet")).toBeNull();
  });

  it("says the list could not be read, rather than that there is nothing", async () => {
    // This page fans out to a query per card: an empty list and a 502 are the
    // same pixels unless the failure is its own state.
    const refetch = vi.fn();
    useOrgTriggersMock.mockReturnValue({
      triggers: [],
      isLoading: false,
      isError: true,
      refetch,
    });
    useRunsMock.mockReturnValue({ runs: [], total: 0, isLoading: false, error: null });
    render(
      <NextIntlClientProvider locale="en" messages={messages}>
        <TooltipProvider>
          <RoutinesWidget title="Routines" hint="" period={PERIOD} />
        </TooltipProvider>
      </NextIntlClientProvider>,
    );

    expect(screen.queryByText("Nothing runs on its own yet")).toBeNull();
    // The failure state must offer the retry, and the retry must reach the query.
    await userEvent.click(screen.getByRole("button", { name: /retry/i }));
    expect(refetch).toHaveBeenCalledOnce();
  });
});
