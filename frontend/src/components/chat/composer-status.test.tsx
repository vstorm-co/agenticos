import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { ComposerStatus } from "./composer-status";

vi.mock("@/components/onboarding/restart-tour-button", () => ({
  RestartTourButton: () => <button type="button">page help</button>,
}));

describe("ComposerStatus", () => {
  it("draws nothing for a live connection, and still reads it aloud", () => {
    // "LIVE" on every message was a reading everybody read past to learn that
    // nothing was wrong.
    render(<ComposerStatus isConnected />);

    const status = screen.getByRole("status");
    expect(status).toHaveTextContent("Live");
    expect(status.className).toBe("sr-only");
  });

  it("draws the word when the connection is gone", () => {
    // A composer that cannot send otherwise looks the same as one that can.
    render(<ComposerStatus isConnected={false} />);

    const status = screen.getByRole("status");
    expect(status.className).not.toContain("sr-only");
    expect(screen.getByText("Offline").className).toContain("text-destructive");
  });

  it("carries the disclaimer and the page help", () => {
    render(<ComposerStatus isConnected />);

    expect(
      screen.getByText("AI can make mistakes. Verify important information."),
    ).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "page help" })).toBeVisible();
  });
});
