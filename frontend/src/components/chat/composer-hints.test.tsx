import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { ComposerHints } from "./composer-hints";

describe("the empty composer hint", () => {
  it("explains both shortcuts without rotating examples", () => {
    const { rerender } = render(<ComposerHints />);
    expect(screen.getByTestId("composer-hints")).toHaveTextContent(
      "Message your agent. / commands · @ resources",
    );
    expect(screen.getByTestId("composer-hints")).toHaveAttribute("aria-hidden", "true");
    rerender(<ComposerHints />);
    expect(screen.getByTestId("composer-hints")).toHaveTextContent(
      "Message your agent. / commands · @ resources",
    );
  });
});
