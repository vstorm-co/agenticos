import { render } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { AnimatedCounter } from "./animated-counter";

/** Answer `prefers-reduced-motion: reduce` for the rest of the test. */
function stopMotion(): void {
  vi.spyOn(window, "matchMedia").mockImplementation(
    (query: string) =>
      ({
        matches: query.includes("prefers-reduced-motion"),
        media: query,
        onchange: null,
        addListener: vi.fn(),
        removeListener: vi.fn(),
        addEventListener: vi.fn(),
        removeEventListener: vi.fn(),
        dispatchEvent: vi.fn(),
      }) as unknown as MediaQueryList,
  );
}

afterEach(() => {
  vi.restoreAllMocks();
});

/**
 * What the counter says out loud.
 *
 * Not `getByText`: every wheel carries all ten faces as real text nodes, so
 * `getByText("0")` matches eleven of them and `getByText("100")` matches none -
 * the digits on screen are whichever faces a transform scrolled into view, and
 * jsdom computes no transforms. `aria-hidden` does not hide a node from
 * `getByText` either. The screen-reader line is the one node holding the value.
 */
function spoken(container: HTMLElement): string {
  return container.querySelector(".sr-only")?.textContent ?? "";
}

describe("AnimatedCounter - the number, however it got there", () => {
  it("spells the value out for a reader who cannot see the wheels", () => {
    const { container } = render(<AnimatedCounter value={1234} />);
    expect(spoken(container)).toBe("1,234");
  });

  it("keeps the decimals it was asked for, including trailing zeroes", () => {
    // `$12.50` losing its zero is what makes a money column ragged.
    const { container } = render(<AnimatedCounter value={12.5} decimals={2} />);
    expect(spoken(container)).toBe("12.50");
  });

  it("rounds to the places it draws rather than dropping them", () => {
    const { container } = render(<AnimatedCounter value={0.12345} decimals={4} />);
    expect(spoken(container)).toBe("0.1235");
  });

  it("draws a sign for a negative and none for zero", () => {
    const { container, rerender } = render(<AnimatedCounter value={-42} />);
    expect(spoken(container)).toBe("-42");

    rerender(<AnimatedCounter value={0} />);
    expect(spoken(container)).toBe("0");
  });

  it("does not sign a negative that rounds away to nothing", () => {
    // `-0.001` at two places is `0.00`, and `-0.00` is a number nobody writes.
    const { container } = render(<AnimatedCounter value={-0.001} decimals={2} />);
    expect(spoken(container)).toBe("0.00");
  });

  it("reads a value that is not a number as zero rather than as NaN", () => {
    // NaN never equals the previous value, so a counter handed one would
    // re-aim every wheel on every render forever.
    const { container } = render(<AnimatedCounter value={Number.NaN} />);
    expect(spoken(container)).toBe("0");
  });

  it("groups in threes by default and in the Indian pattern when asked", () => {
    const { container, rerender } = render(<AnimatedCounter value={1234567} />);
    expect(spoken(container)).toBe("1,234,567");

    rerender(<AnimatedCounter value={1234567} grouping="indian" />);
    expect(spoken(container)).toBe("12,34,567");
  });

  it("leaves the digits unbroken when the separator is empty", () => {
    const { container } = render(<AnimatedCounter value={1234567} separator="" />);
    expect(spoken(container)).toBe("1234567");
  });

  it("groups an Indian number too short to have a head", () => {
    const { container } = render(<AnimatedCounter value={123} grouping="indian" />);
    expect(spoken(container)).toBe("123");
  });

  it("takes the locale's own separators", () => {
    const { container } = render(
      <AnimatedCounter value={1234.5} decimals={1} separator=" " decimalSeparator="," />,
    );
    expect(spoken(container)).toBe("1 234,5");
  });

  it("pads to a fixed width so a counter does not resize as it climbs", () => {
    const { container } = render(<AnimatedCounter value={7} padStart={3} />);
    expect(spoken(container)).toBe("007");
  });

  it("clamps decimals and padding rather than drawing an unbounded row of wheels", () => {
    const { container, rerender } = render(<AnimatedCounter value={1} decimals={99} />);
    // 15 places is the ceiling; one wheel per digit past that is a hang, not a figure.
    expect(spoken(container)).toBe(`1.${"0".repeat(15)}`);

    rerender(<AnimatedCounter value={1} padStart={-5} />);
    expect(spoken(container)).toBe("1");
  });

  it("says the caller's label instead of the digits when it has one", () => {
    // The unit lives in `prefix`, which is aria-hidden with the wheels - so the
    // digits alone would be announced as a bare number with no currency.
    const { container } = render(<AnimatedCounter value={42} prefix="$" label="42 US dollars" />);
    expect(spoken(container)).toBe("42 US dollars");
  });

  it("draws the prefix and suffix it is given", () => {
    const { container } = render(<AnimatedCounter value={9} prefix="$" suffix="/mo" />);
    expect(container.textContent).toContain("$");
    expect(container.textContent).toContain("/mo");
  });

  it("re-aims its wheels when the value moves, in either direction", () => {
    const { container, rerender } = render(<AnimatedCounter value={10} />);
    rerender(<AnimatedCounter value={90} />);
    expect(spoken(container)).toBe("90");

    rerender(<AnimatedCounter value={20} />);
    expect(spoken(container)).toBe("20");
  });

  it("gains and loses places without losing the number", () => {
    const { container, rerender } = render(<AnimatedCounter value={99} />);
    rerender(<AnimatedCounter value={100} />);
    expect(spoken(container)).toBe("100");

    rerender(<AnimatedCounter value={9} />);
    expect(spoken(container)).toBe("9");
  });

  it("caps a value past the safe integer range rather than turning exponential", () => {
    // `String(1e21)` is "1e+21", and every character of that becomes a cell.
    const { container } = render(<AnimatedCounter value={1e21} />);
    expect(spoken(container)).toMatch(/^[\d,]+$/);
  });

  it("sets its wheels rather than rolling them when motion is turned down", () => {
    // Not a nicety: `prefers-reduced-motion` is set by people for whom a
    // spinning column is a symptom, and a counter is the one thing on a
    // dashboard that moves without being asked to.
    stopMotion();
    const { container, rerender } = render(<AnimatedCounter value={1} />);
    rerender(<AnimatedCounter value={8} />);
    expect(spoken(container)).toBe("8");
  });

  it("still gains and loses places with motion turned down", () => {
    stopMotion();
    const { container, rerender } = render(<AnimatedCounter value={9} />);
    rerender(<AnimatedCounter value={10} />);
    expect(spoken(container)).toBe("10");
  });
});
