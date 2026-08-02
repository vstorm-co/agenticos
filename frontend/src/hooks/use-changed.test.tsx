import { act, renderHook } from "@testing-library/react";
import { useState } from "react";
import { describe, expect, it } from "vitest";

import { useChanged } from "./use-changed";

/**
 * Asserted through the state it guards, not on its return value.
 *
 * `useChanged` is true for exactly one render pass, and writing state during
 * render makes React discard that pass and re-run the component before
 * committing. So a test reading the boolean afterwards always sees `false`, and
 * a render log counts the discarded pass as well - neither says anything about
 * what a user would see. What the hook promises is the reset, so that is what
 * these check.
 */
function useGuardedDraft(config: string) {
  const [draft, setDraft] = useState(config);
  if (useChanged(config)) setDraft(config);
  return { draft, setDraft };
}

describe("useChanged", () => {
  it("re-seeds the state it guards when the key moves", () => {
    const { result, rerender } = renderHook(({ config }) => useGuardedDraft(config), {
      initialProps: { config: "first" },
    });
    act(() => result.current.setDraft("edited"));

    rerender({ config: "second" });

    expect(result.current.draft).toBe("second");
  });

  it("leaves an edit alone while the key stays put", () => {
    // The half that matters more: a form that re-seeded on every render would
    // take the text out from under whoever was typing it.
    const { result, rerender } = renderHook(({ config }) => useGuardedDraft(config), {
      initialProps: { config: "first" },
    });
    act(() => result.current.setDraft("edited"));

    rerender({ config: "first" });
    rerender({ config: "first" });

    expect(result.current.draft).toBe("edited");
  });

  it("compares with Object.is, so an equal object still counts as a change", () => {
    // Reference equality, and the reason the docstring tells callers watching
    // several fields to build a string rather than an object.
    const { result, rerender } = renderHook(
      ({ config }) => {
        const [seen, setSeen] = useState(0);
        if (useChanged(config)) setSeen((n) => n + 1);
        return seen;
      },
      { initialProps: { config: { id: 1 } } },
    );

    rerender({ config: { id: 1 } });

    expect(result.current).toBe(1);
  });
});
