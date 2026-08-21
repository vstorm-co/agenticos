import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { TriggerTemplatePicker } from "./trigger-template-picker";
import type { TriggerTemplate } from "@/types/trigger-templates";

let templates: TriggerTemplate[] = [];
let isLoading = false;

vi.mock("@/hooks", () => ({
  useTriggerTemplates: () => ({ templates, isLoading, error: null }),
}));

const DAILY: TriggerTemplate = {
  key: "daily-standup",
  label: "Daily standup",
  description: "Summarise overnight activity",
  prompt: "Summarise what happened overnight.",
  trigger_type: "schedule",
  suggested_cadence: { schedule_kind: "interval", interval_seconds: 86400 },
};

const GITHUB_TRIAGE: TriggerTemplate = {
  key: "github-triage",
  label: "Triage the new issue",
  description: "Propose a priority and labels",
  prompt: "Triage this issue.",
  trigger_type: "event",
  event_source: "github",
};

const EMAIL_REPLY: TriggerTemplate = {
  key: "email-reply",
  label: "Draft a reply",
  description: "Answer the sender",
  prompt: "Draft a reply.",
  trigger_type: "event",
  event_source: "gmail",
};

beforeEach(() => {
  templates = [];
  isLoading = false;
});

describe("TriggerTemplatePicker", () => {
  it("renders nothing while the catalog is loading", () => {
    isLoading = true;
    const { container } = render(
      <TriggerTemplatePicker
        triggerType="schedule"
        selectedKey={null}
        onPick={vi.fn()}
        onScratch={vi.fn()}
      />,
    );

    expect(container).toBeEmptyDOMElement();
  });

  it("renders nothing when no template fits the flow it sits in", () => {
    // The catalog is not empty - it just holds nothing for this mode, which
    // must read the same as an empty catalog: the blank form, no empty shell.
    templates = [GITHUB_TRIAGE];
    const { container } = render(
      <TriggerTemplatePicker
        triggerType="schedule"
        selectedKey={null}
        onPick={vi.fn()}
        onScratch={vi.fn()}
      />,
    );

    expect(container).toBeEmptyDOMElement();
  });

  it("offers each schedule template and a start-from-scratch option", async () => {
    const user = userEvent.setup();
    templates = [DAILY, GITHUB_TRIAGE];
    const onPick = vi.fn();
    const onScratch = vi.fn();
    render(
      <TriggerTemplatePicker
        triggerType="schedule"
        selectedKey={null}
        onPick={onPick}
        onScratch={onScratch}
      />,
    );

    // An event card never crosses into the schedule flow.
    expect(screen.queryByRole("button", { name: /Triage the new issue/ })).toBeNull();

    await user.click(screen.getByRole("button", { name: /Daily standup/ }));
    expect(onPick).toHaveBeenCalledWith(DAILY);

    await user.click(screen.getByRole("button", { name: /Start from scratch/ }));
    expect(onScratch).toHaveBeenCalledTimes(1);
  });

  it("offers only the picked source's event templates", () => {
    templates = [DAILY, GITHUB_TRIAGE, EMAIL_REPLY];
    render(
      <TriggerTemplatePicker
        triggerType="event"
        eventSource="gmail"
        selectedKey={null}
        onPick={vi.fn()}
        onScratch={vi.fn()}
      />,
    );

    // A prompt written for a GitHub issue makes no sense against an inbound
    // email, so neither the schedule card nor the other source's shows.
    expect(screen.getByRole("button", { name: /Draft a reply/ })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Triage the new issue/ })).toBeNull();
    expect(screen.queryByRole("button", { name: /Daily standup/ })).toBeNull();
  });

  it("marks the picked template as pressed", () => {
    templates = [DAILY];
    render(
      <TriggerTemplatePicker
        triggerType="schedule"
        selectedKey="daily-standup"
        onPick={vi.fn()}
        onScratch={vi.fn()}
      />,
    );

    expect(screen.getByRole("button", { name: /Daily standup/ })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
    expect(screen.getByRole("button", { name: /Start from scratch/ })).toHaveAttribute(
      "aria-pressed",
      "false",
    );
  });
});
