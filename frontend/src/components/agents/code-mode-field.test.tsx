import { fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { NextIntlClientProvider } from "next-intl";
import { describe, expect, it, vi } from "vitest";

import messages from "../../../messages/en.json";
import { CODE_MODE_DEFAULTS, CodeModeField } from "./code-mode-field";
import type { CodeModeSpec } from "@/types/agents";

function show(value: CodeModeSpec | undefined, onChange = vi.fn()) {
  render(
    <NextIntlClientProvider locale="en" messages={messages}>
      <CodeModeField value={value} onChange={onChange} disabled={false} />
    </NextIntlClientProvider>,
  );
  return onChange;
}

describe("CodeModeField", () => {
  it("is off for an agent that never set it, with no limit to set", () => {
    show(undefined);
    expect(screen.getByRole("switch", { name: "Code mode" })).not.toBeChecked();
    expect(screen.queryByLabelText("Tool calls per script")).toBeNull();
  });

  it("switches on", async () => {
    const onChange = show(CODE_MODE_DEFAULTS);
    await userEvent.click(screen.getByRole("switch", { name: "Code mode" }));
    expect(onChange).toHaveBeenCalledWith({ enabled: true, max_tool_calls: 100 });
  });

  it("sets the calls a script may make, back to the default when cleared", () => {
    const onChange = show({ enabled: true, max_tool_calls: 100 });
    fireEvent.change(screen.getByLabelText("Tool calls per script"), { target: { value: "25" } });
    expect(onChange).toHaveBeenLastCalledWith({ enabled: true, max_tool_calls: 25 });
    fireEvent.change(screen.getByLabelText("Tool calls per script"), { target: { value: "" } });
    expect(onChange).toHaveBeenLastCalledWith({ enabled: true, max_tool_calls: 100 });
  });
});
