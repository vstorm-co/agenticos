import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ScheduleTemplatePicker } from "./schedule-template-picker";
import type { ScheduleTemplate } from "@/types/schedule-templates";

let templates: ScheduleTemplate[] = [];
let isLoading = false;

vi.mock("@/hooks", () => ({
  useScheduleTemplates: () => ({ templates, isLoading, error: null }),
}));

const DAILY: ScheduleTemplate = {
  key: "daily-standup",
  label: "Daily standup",
  description: "Summarise overnight activity",
  prompt: "Summarise what happened overnight.",
  suggested_cadence: { schedule_kind: "interval", interval_seconds: 86400 },
};

beforeEach(() => {
  templates = [];
  isLoading = false;
});

describe("ScheduleTemplatePicker", () => {
  it("renders nothing while the catalog is loading", () => {
    isLoading = true;
    const { container } = render(
      <ScheduleTemplatePicker selectedKey={null} onPick={vi.fn()} onScratch={vi.fn()} />,
    );

    expect(container).toBeEmptyDOMElement();
  });

  it("renders nothing when there are no templates", () => {
    templates = [];
    const { container } = render(
      <ScheduleTemplatePicker selectedKey={null} onPick={vi.fn()} onScratch={vi.fn()} />,
    );

    expect(container).toBeEmptyDOMElement();
  });

  it("offers each template and a start-from-scratch option", async () => {
    const user = userEvent.setup();
    templates = [DAILY];
    const onPick = vi.fn();
    const onScratch = vi.fn();
    render(<ScheduleTemplatePicker selectedKey={null} onPick={onPick} onScratch={onScratch} />);

    await user.click(screen.getByRole("button", { name: /Daily standup/ }));
    expect(onPick).toHaveBeenCalledWith(DAILY);

    await user.click(screen.getByRole("button", { name: /Start from scratch/ }));
    expect(onScratch).toHaveBeenCalledTimes(1);
  });

  it("marks the picked template as pressed", () => {
    templates = [DAILY];
    render(
      <ScheduleTemplatePicker selectedKey="daily-standup" onPick={vi.fn()} onScratch={vi.fn()} />,
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
