import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { RetentionForm } from "./retention-form";
import type { RetentionPolicy } from "@/lib/retention-api";

vi.mock("next-intl", () => ({
  useTranslations:
    () =>
    (key: string, values?: Record<string, string | number>): string =>
      values ? `${key}:${Object.values(values).join(",")}` : key,
}));

function policy(overrides: Partial<RetentionPolicy> = {}): RetentionPolicy {
  return {
    requested: {},
    effective: { audit: 2190 },
    ceilings: {},
    audit_floor_days: 2190,
    conflicts: [],
    ...overrides,
  };
}

function renderForm(over: Partial<RetentionPolicy> = {}, onSave = vi.fn()) {
  render(<RetentionForm policy={policy(over)} isSaving={false} saved={false} onSave={onSave} />);
  return onSave;
}

describe("the retention form", () => {
  it("shows a row per class", () => {
    renderForm();

    expect(screen.getAllByRole("spinbutton")).toHaveLength(6);
  });

  it("says what actually sweeps beside what was asked for", () => {
    // A ceiling cuts a longer period, so the number that sweeps is frequently
    // not the number in the box - and a page showing only one is one somebody
    // argues with.
    renderForm({
      requested: { conversations: 3650 },
      effective: { conversations: 365, audit: 2190 },
      ceilings: { conversations: 365 },
    });

    expect(screen.getByText("cappedByDeployment:365")).toBeInTheDocument();
    expect(screen.getByText("atLeastDays:2190")).toBeInTheDocument();
  });

  it("says the plain period where nothing bounded it", () => {
    renderForm({ requested: { runs: 90 }, effective: { runs: 90, audit: 2190 } });

    expect(screen.getByText("afterDays:90")).toBeInTheDocument();
  });

  it("calls an empty box for ever rather than missing", () => {
    // `null` and unset differ on the wire, and this form means `null`.
    renderForm({ effective: { conversations: null, audit: 2190 } });

    expect(screen.getAllByText("keptForEver").length).toBeGreaterThan(0);
  });

  it("sends nothing at all when nothing was typed", async () => {
    // An empty box means two different things - "nothing has been said about
    // this class" and "keep for ever, deliberately" - and only the typing tells
    // them apart. Sending `null` for every empty box turned opening the page and
    // saving into overriding every deployment default with "for ever".
    const onSave = renderForm({ requested: { conversations: 30 } });

    await userEvent.click(screen.getByRole("button", { name: "save" }));

    expect(onSave).toHaveBeenCalledWith({});
  });

  it("sends null for a box the person cleared, and that alone", async () => {
    const onSave = renderForm({ requested: { conversations: 30, runs: 90 } });

    await userEvent.clear(screen.getByLabelText("classes.conversations"));
    await userEvent.click(screen.getByRole("button", { name: "save" }));

    expect(onSave).toHaveBeenCalledWith({ conversations: null });
  });

  it("sends what was typed, not what was loaded", async () => {
    const onSave = renderForm({ requested: { runs: 30 } });
    const box = screen.getByLabelText("classes.runs");

    await userEvent.clear(box);
    await userEvent.type(box, "90");
    await userEvent.click(screen.getByRole("button", { name: "save" }));

    expect(onSave.mock.calls[0]?.[0]).toEqual({ runs: 90 });
  });

  it("follows the policy the server answered with, not what was typed at it", async () => {
    // A save comes back with what the ceiling made of the period, so the box has
    // to move to it - otherwise the form keeps showing a number nothing applies.
    const { rerender } = render(
      <RetentionForm
        policy={policy({ requested: { runs: 30 } })}
        isSaving={false}
        saved={false}
        onSave={vi.fn()}
      />,
    );
    const box = screen.getByLabelText("classes.runs");
    await userEvent.clear(box);
    await userEvent.type(box, "3650");

    rerender(
      <RetentionForm
        policy={policy({ requested: { runs: 365 } })}
        isSaving={false}
        saved={false}
        onSave={vi.fn()}
      />,
    );

    expect(screen.getByLabelText("classes.runs")).toHaveValue(365);
  });

  it("names the deployment's own contradiction rather than picking one", () => {
    // An audit ceiling below the audit floor asks for a trail kept six years and
    // deleted after one; resolving it silently leaves a deployment behaving
    // unlike its own settings page.
    renderForm({ conflicts: ["audit"] });

    expect(screen.getByText("conflictingBounds:audit")).toBeInTheDocument();
  });

  it("says nothing about a save nobody made", () => {
    renderForm();

    expect(screen.queryByText("saved")).not.toBeInTheDocument();
  });

  it("disables the button while a save is in flight", () => {
    render(<RetentionForm policy={policy()} isSaving saved onSave={vi.fn()} />);

    expect(screen.getByRole("button", { name: "saving" })).toBeDisabled();
    expect(screen.getByText("saved")).toBeInTheDocument();
  });
});
