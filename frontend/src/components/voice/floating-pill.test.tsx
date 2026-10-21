import { render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { FloatingPill } from "./floating-pill";

const motionState = vi.hoisted(() => ({ reduced: false }));
vi.mock("@/hooks/use-reduced-motion", () => ({ useReducedMotion: () => motionState.reduced }));

beforeEach(() => {
  motionState.reduced = false;
});

describe("FloatingPill", () => {
  it("holds nothing until there is a pill, then the pill, then nothing again", async () => {
    const { rerender } = render(<FloatingPill pill={null} />);
    expect(screen.queryByTestId("floating-pill")).toBeNull();

    rerender(<FloatingPill pill={{ key: "call", node: <span>On a call</span> }} />);
    expect(screen.getByTestId("floating-pill")).toHaveTextContent("On a call");
    expect(screen.getByTestId("floating-pill")).toHaveAttribute("data-floating-pill");

    rerender(<FloatingPill pill={null} />);
    await waitFor(() => expect(screen.queryByTestId("floating-pill")).toBeNull());
  });

  it("swaps one pill for another by its key", async () => {
    const { rerender } = render(
      <FloatingPill pill={{ key: "dictation", node: <span>Dictating</span> }} />,
    );
    rerender(<FloatingPill pill={{ key: "call", node: <span>On a call</span> }} />);
    await waitFor(() => expect(screen.queryByText("Dictating")).toBeNull());
    expect(screen.getByText("On a call")).toBeInTheDocument();
  });

  it("appears and leaves at once under reduced motion", () => {
    motionState.reduced = true;
    const { rerender } = render(
      <FloatingPill pill={{ key: "call", node: <span>On a call</span> }} />,
    );
    expect(screen.getByText("On a call")).toBeInTheDocument();
    rerender(<FloatingPill pill={null} />);
  });
});
