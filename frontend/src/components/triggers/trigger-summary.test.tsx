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

  it("reads a cron schedule by its expression", () => {
    render(
      <TriggerSummary
        trigger={trigger({
          schedule_kind: "cron",
          interval_seconds: null,
          cron_expression: "0 9 * * *",
        })}
      />,
    );
    expect(screen.getByText("Cron 0 9 * * * (UTC)")).toBeInTheDocument();
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
