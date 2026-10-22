import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { ComposerStatus } from "./composer-status";

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
    render(<ComposerStatus isConnected={false} compact />);

    const status = screen.getByRole("status");
    expect(status.className).not.toContain("sr-only");
    expect(status).toHaveTextContent("Offline");
    expect(status.className).toContain("text-destructive");
  });

  it("carries no disclaimer and no page help (#2301)", () => {
    render(<ComposerStatus isConnected={false} />);

    expect(screen.queryByText(/AI can make mistakes/)).not.toBeInTheDocument();
    expect(screen.queryByRole("button")).not.toBeInTheDocument();
  });
});
