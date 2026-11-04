import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { ComposerStatus } from "./composer-status";

describe("ComposerStatus", () => {
  it.each([
    [true, "Live"],
    [false, "Offline"],
  ])("reads the connection aloud and draws nothing (connected: %s)", (isConnected, said) => {
    // The box says it is reconnecting; a red line under it said it twice (#2301).
    render(<ComposerStatus isConnected={isConnected} />);

    const status = screen.getByRole("status");
    expect(status).toHaveTextContent(said);
    expect(status.className).toBe("sr-only");
  });

  it("carries no disclaimer and no page help (#2301)", () => {
    render(<ComposerStatus isConnected={false} />);

    expect(screen.queryByText(/AI can make mistakes/)).not.toBeInTheDocument();
    expect(screen.queryByRole("button")).not.toBeInTheDocument();
  });
});
