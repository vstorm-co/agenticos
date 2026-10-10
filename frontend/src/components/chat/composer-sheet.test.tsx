import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { ComposerSheet } from "./composer-sheet";

describe("the phone composer's sheet", () => {
  it("opens from its `+` and closes on the action picked", () => {
    const onAttach = vi.fn();
    const onVoice = vi.fn();
    render(<ComposerSheet onAttach={onAttach} onVoice={onVoice} />);
    expect(screen.queryByRole("dialog")).toBeNull();

    fireEvent.click(screen.getByRole("button", { name: "Add to message" }));
    fireEvent.click(screen.getByRole("button", { name: "Attach file" }));
    expect(onAttach).toHaveBeenCalledOnce();
    expect(screen.queryByRole("dialog")).toBeNull();

    fireEvent.click(screen.getByRole("button", { name: "Add to message" }));
    fireEvent.click(screen.getByRole("button", { name: "Voice input" }));
    expect(onVoice).toHaveBeenCalledOnce();
  });

  it("is a full-width sheet up from the bottom edge, clear of the home indicator", () => {
    render(<ComposerSheet onAttach={vi.fn()} onVoice={vi.fn()} />);

    fireEvent.click(screen.getByRole("button", { name: "Add to message" }));

    expect(screen.getByRole("dialog")).toHaveClass(
      "inset-x-0",
      "bottom-0",
      "pb-[env(safe-area-inset-bottom)]",
    );
  });

  it("cannot be opened while the composer is disabled", () => {
    render(<ComposerSheet onAttach={vi.fn()} onVoice={vi.fn()} disabled />);

    expect(screen.getByRole("button", { name: "Add to message" })).toBeDisabled();
  });
});
