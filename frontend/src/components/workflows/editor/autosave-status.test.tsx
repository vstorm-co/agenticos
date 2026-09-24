import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { AutosaveStatusIndicator } from "./autosave-status";
import type { AutosaveStatus } from "./use-workflow-autosave";

describe("AutosaveStatusIndicator", () => {
  it.each<[Exclude<AutosaveStatus, "idle">, string]>([
    ["pending", "Unsaved changes"],
    ["saving", "Saving…"],
    ["saved", "Saved"],
    ["conflict", "Draft changed elsewhere"],
    ["error", "Save failed — will retry"],
  ])("shows the %s copy", (status, copy) => {
    render(<AutosaveStatusIndicator status={status} />);
    expect(screen.getByRole("status")).toHaveTextContent(copy);
    expect(screen.getByRole("status")).toHaveAttribute("data-autosave-status", status);
  });

  it("renders nothing readable in the idle state", () => {
    render(<AutosaveStatusIndicator status="idle" />);
    const region = screen.getByRole("status");
    expect(region).toHaveAttribute("data-autosave-status", "idle");
    expect(region).toHaveTextContent("");
  });
});
