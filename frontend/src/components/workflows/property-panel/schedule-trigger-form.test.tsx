import { fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import type { NodeInstance } from "@/lib/workflows/types";

import { ScheduleTriggerForm } from "./schedule-trigger-form";

function node(config: Record<string, unknown> = {}): NodeInstance {
  return {
    id: "n1",
    definition_id: "trigger.schedule",
    definition_version: 1,
    config,
    layout: { x: 0, y: 0 },
  };
}

describe("ScheduleTriggerForm", () => {
  it("writes a cadence into the node's config as soon as it schedules", async () => {
    const update = vi.fn();
    render(<ScheduleTriggerForm node={node({ input: { a: 1 } })} updateNodeConfig={update} />);

    fireEvent.change(screen.getByLabelText("Every"), { target: { value: "2" } });
    expect(update).toHaveBeenLastCalledWith("n1", {
      input: { a: 1 },
      schedule_kind: "interval",
      interval_seconds: 7200,
      cron_expression: null,
    });

    // A count that could never be scheduled keeps the last good one, and says why.
    update.mockClear();
    fireEvent.change(screen.getByLabelText("Every"), { target: { value: "0" } });
    expect(update).not.toHaveBeenCalled();
    expect(screen.getByText(/Pick a cadence of at least a minute/)).toBeTruthy();

    await userEvent.click(screen.getByRole("combobox", { name: "Unit" }));
    await userEvent.click(screen.getByRole("option", { name: "Days" }));
    await userEvent.click(screen.getByRole("combobox", { name: "Runs" }));
    await userEvent.click(screen.getByRole("option", { name: "Daily at a set time" }));
    fireEvent.change(screen.getByLabelText("Time"), { target: { value: "07:30" } });
    expect(update).toHaveBeenLastCalledWith("n1", {
      input: { a: 1 },
      schedule_kind: "cron",
      cron_expression: "30 7 * * *",
      interval_seconds: null,
    });

    await userEvent.click(screen.getByRole("combobox", { name: "Runs" }));
    await userEvent.click(screen.getByRole("option", { name: "On a cron expression" }));
    fireEvent.change(screen.getByLabelText("Cron expression"), { target: { value: "0 9 * * 1" } });
    expect(update).toHaveBeenLastCalledWith(
      "n1",
      expect.objectContaining({ cron_expression: "0 9 * * 1" }),
    );
  });

  it("opens on what the node holds, and writes the input only while it is an object", () => {
    const update = vi.fn();
    render(
      <ScheduleTriggerForm
        node={node({ schedule_kind: "cron", cron_expression: "15 6 * * *", input: { r: "eu" } })}
        updateNodeConfig={update}
      />,
    );
    expect(screen.getByLabelText("Time")).toHaveProperty("value", "06:15");
    const input = screen.getByRole("textbox", { name: "Input" });
    expect(input).toHaveProperty("value", JSON.stringify({ r: "eu" }, null, 2));

    fireEvent.change(input, { target: { value: "[1]" } });
    expect(update).not.toHaveBeenCalled();
    fireEvent.change(input, { target: { value: '{"r": "us"}' } });
    expect(update).toHaveBeenLastCalledWith("n1", expect.objectContaining({ input: { r: "us" } }));
  });

  it("starts an empty node on the hourly default", () => {
    render(<ScheduleTriggerForm node={node()} updateNodeConfig={vi.fn()} disabled />);
    expect(screen.getByLabelText("Every")).toHaveProperty("value", "1");
    expect(screen.getByLabelText("Every")).toHaveProperty("disabled", true);
  });
});
