import { fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { NextIntlClientProvider } from "next-intl";
import { describe, expect, it, vi } from "vitest";

import messages from "../../../messages/en.json";
import { LOOP_GUARD_DEFAULTS, LoopGuardFields } from "./loop-guard-fields";
import type { LoopGuardSpec } from "@/types/agents";

function show(value: LoopGuardSpec | undefined, onChange = vi.fn()) {
  render(
    <NextIntlClientProvider locale="en" messages={messages}>
      <LoopGuardFields value={value} onChange={onChange} disabled={false} />
    </NextIntlClientProvider>,
  );
  return onChange;
}

describe("LoopGuardFields", () => {
  it("shows the server's defaults for an agent that never set them", () => {
    show(undefined);
    expect(screen.getByRole("switch", { name: "Stop tool-call loops" })).toBeChecked();
    expect(screen.getByLabelText("Identical calls in a row")).toHaveValue(4);
    expect(screen.getByLabelText("Cycle repeats")).toHaveValue(3);
  });

  it("changes a threshold, and falls back to its default when cleared", () => {
    const onChange = show(LOOP_GUARD_DEFAULTS);
    fireEvent.change(screen.getByLabelText("Identical calls in a row"), { target: { value: "6" } });
    expect(onChange).toHaveBeenLastCalledWith({ enabled: true, repeats: 6, cycles: 3 });
    fireEvent.change(screen.getByLabelText("Cycle repeats"), { target: { value: "" } });
    expect(onChange).toHaveBeenLastCalledWith({ enabled: true, repeats: 4, cycles: 3 });
  });

  it("switches the guard off and hides the thresholds", async () => {
    const onChange = show(LOOP_GUARD_DEFAULTS);
    await userEvent.click(screen.getByRole("switch", { name: "Stop tool-call loops" }));
    expect(onChange).toHaveBeenCalledWith({ enabled: false, repeats: 4, cycles: 3 });
  });

  it("hides the thresholds while it is off", () => {
    show({ ...LOOP_GUARD_DEFAULTS, enabled: false });
    expect(screen.queryByLabelText("Cycle repeats")).toBeNull();
  });
});
