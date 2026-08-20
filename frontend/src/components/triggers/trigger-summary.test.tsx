import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { TriggerSummary } from "./trigger-summary";
import type { Trigger } from "@/types/triggers";

function trigger(overrides: Partial<Trigger> = {}): Trigger {
  return {
    id: "t1",
    agent_id: "a1",
    agent_name: null,
    name: null,
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
    prompt: "run",
    next_fire_at: null,
    last_fired_at: null,
    last_run_id: null,
    conversation_id: null,
    webhook_url: null,
    created_at: null,
    updated_at: null,
    ...overrides,
  };
}

describe("TriggerSummary", () => {
  it("reads an interval in minutes", () => {
    render(<TriggerSummary trigger={trigger({ interval_seconds: 900 })} />);
    expect(screen.getByText("Every 15 minutes")).toBeInTheDocument();
  });

  it("reads an interval in hours", () => {
    render(<TriggerSummary trigger={trigger({ interval_seconds: 7200 })} />);
    expect(screen.getByText("Every 2 hours")).toBeInTheDocument();
  });

  it("reads an interval in days", () => {
    render(<TriggerSummary trigger={trigger({ interval_seconds: 86400 })} />);
    expect(screen.getByText("Every day")).toBeInTheDocument();
  });

  it("reads a daily cron in plain language", () => {
    render(
      <TriggerSummary
        trigger={trigger({
          schedule_kind: "cron",
          interval_seconds: null,
          cron_expression: "0 9 * * *",
        })}
      />,
    );
    expect(screen.getByText("Daily at 09:00 UTC")).toBeInTheDocument();
  });

  it("reads a weekday cron as its days, Monday-first", () => {
    render(
      <TriggerSummary
        trigger={trigger({
          schedule_kind: "cron",
          interval_seconds: null,
          // Cron numbers Sunday 0, but the summary lists the picker's order.
          cron_expression: "0 9 * * 0,1,2",
        })}
      />,
    );
    expect(screen.getByText("At 09:00 UTC on Mon, Tue, Sun")).toBeInTheDocument();
  });

  it("reads a monthly cron by its day", () => {
    render(
      <TriggerSummary
        trigger={trigger({
          schedule_kind: "cron",
          interval_seconds: null,
          cron_expression: "30 18 15 * *",
        })}
      />,
    );
    expect(screen.getByText("Monthly on day 15 at 18:30 UTC")).toBeInTheDocument();
  });

  it("reads an every-N-days cron exactly like an interval in days", () => {
    render(
      <TriggerSummary
        trigger={trigger({
          schedule_kind: "cron",
          interval_seconds: null,
          cron_expression: "0 9 */2 * *",
        })}
      />,
    );
    expect(screen.getByText("Every 2 days")).toBeInTheDocument();
  });

  it("shows raw notation only for a hand-written Advanced expression", () => {
    render(
      <TriggerSummary
        trigger={trigger({
          schedule_kind: "cron",
          interval_seconds: null,
          cron_expression: "*/5 * * * *",
        })}
      />,
    );
    expect(screen.getByText("Cron */5 * * * * (UTC)")).toBeInTheDocument();
  });

  it("names a GitHub event trigger", () => {
    render(
      <TriggerSummary
        trigger={trigger({ trigger_type: "event", event_source: "github", interval_seconds: null })}
      />,
    );
    expect(screen.getByText("On new GitHub issues")).toBeInTheDocument();
  });

  it("names an email event trigger", () => {
    render(
      <TriggerSummary
        trigger={trigger({ trigger_type: "event", event_source: "email", interval_seconds: null })}
      />,
    );
    expect(screen.getByText("On inbound email")).toBeInTheDocument();
  });

  it("reads a portal preset in plain language with its target", () => {
    render(
      <TriggerSummary
        trigger={trigger({
          trigger_type: "event",
          event_source: "github",
          interval_seconds: null,
          portal_key: "github",
          provider_target: "acme/repo",
        })}
      />,
    );
    expect(screen.getByText("New issue in acme/repo")).toBeInTheDocument();
  });

  it("falls back to the generic source label for a preset with no target", () => {
    render(
      <TriggerSummary
        trigger={trigger({
          trigger_type: "event",
          event_source: "github",
          interval_seconds: null,
          portal_key: "github",
        })}
      />,
    );
    expect(screen.getByText("On new GitHub issues")).toBeInTheDocument();
  });

  it("names an API event trigger", () => {
    render(
      <TriggerSummary
        trigger={trigger({
          trigger_type: "event",
          event_source: "webhook",
          interval_seconds: null,
        })}
      />,
    );
    expect(screen.getByText("On an API delivery")).toBeInTheDocument();
  });
});
