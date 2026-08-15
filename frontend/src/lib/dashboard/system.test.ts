import { describe, expect, it } from "vitest";

import {
  AREA_FILL_OPACITY,
  BAND_GAP,
  CARD_GAP,
  CARD_STACK,
  HEADING_GAP,
  LINE_WIDTH,
  MARK_CLASS,
  QUIET_SURFACE,
  TRACK_CLASS,
} from "./system";

/**
 * Asserting a constant equals its own literal tests nothing. What is worth
 * holding shut is the *relationship* between them - which is the thing that was
 * actually broken, and the thing a future edit can quietly break again.
 */

/** The number in a Tailwind spacing class, in 4px units (`gap-4` → 4 → 16px). */
const steps = (className: string): number => Number(className.split("-").pop());

describe("the dashboard's rhythm", () => {
  it("puts a band further from its neighbour than a card is from its own", () => {
    // The defect this system exists for: band-to-band was 24px against
    // card-to-card's 16px, so five bands read as one mass. Whatever the values
    // become, the hierarchy has to survive - and by a margin a reader can see,
    // not by the eight pixels it used to be.
    expect(steps(BAND_GAP)).toBeGreaterThanOrEqual(steps(CARD_GAP) * 2);
  });

  it("keeps a card's own contents tighter than the gap between cards", () => {
    // Otherwise two cards read as one, or one card reads as two.
    expect(steps(CARD_STACK)).toBeLessThan(steps(CARD_GAP));
    expect(steps(HEADING_GAP)).toBeLessThan(steps(CARD_GAP));
  });
});

describe("the dashboard's data ink", () => {
  it("draws a mark and its track in different tokens", () => {
    // A bar with the same fill and track has no visible extent.
    expect(MARK_CLASS).not.toBe(TRACK_CLASS);
  });

  it("names a role for every ink, never a palette step or a raw colour", () => {
    // Layer 2 of `globals.css`: a component writes what a colour *means*, so a
    // retheme is one variable. `bg-brand-500` or `bg-[#3581f6]` would pin it.
    for (const ink of [MARK_CLASS, TRACK_CLASS, QUIET_SURFACE]) {
      expect(ink).not.toMatch(/\d/);
      expect(ink).not.toMatch(/[[#]/);
    }
  });

  it("keeps an area a wash rather than a block", () => {
    // A saturated fill under a line is the "thick saturated blocks" anti-pattern;
    // the spec is a tenth, and the previous 0.25 gradient was two and a half
    // times it.
    expect(AREA_FILL_OPACITY).toBeLessThanOrEqual(0.12);
    expect(LINE_WIDTH).toBe(2);
  });
});
